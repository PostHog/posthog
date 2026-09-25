import { DataLoadError } from './data-loader'
import { HostBridge } from './host-bridge'
import { MetadataFooter } from './metadata-footer'
import { PlaybackController } from './playback-controller'
import { METADATA_FOOTER_HEIGHT_PX } from './protocol'
import { createReplayers } from './replayer-factory'
import type { PlayerConfig } from './types'
import { ViewportScaler } from './viewport-scaler'

async function init(config: PlayerConfig, bridge: HostBridge): Promise<void> {
    const contentEl = document.querySelector('.PlayerFrame__content') as HTMLElement

    const setup = await createReplayers(config, contentEl, bridge)
    if (setup === 'no_snapshots' || setup === 'no_full_snapshot') {
        // Blocks can still be landing when nothing loaded, so that stays retryable. Loaded snapshots without a full
        // snapshot never gain one on a retry, and each attempt would render the same blank video.
        const noFullSnapshot = setup === 'no_full_snapshot'
        bridge.setError({
            code: 'NO_SNAPSHOTS',
            message: noFullSnapshot ? 'No window has a full snapshot to render' : 'No snapshots after processing',
            retryable: !noFullSnapshot,
        })
        bridge.signalEnded()
        return
    }

    const { windows, segments, firstTimestamp } = setup

    const footerHeight = config.showMetadataFooter ? METADATA_FOOTER_HEIGHT_PX : 0
    const scaler = new ViewportScaler(contentEl, footerHeight)

    const controller = new PlaybackController(
        windows,
        segments,
        firstTimestamp,
        {
            skipInactivity: config.skipInactivity,
            endOffsetS: config.endOffsetS,
        },
        bridge
    )
    for (const tab of windows) {
        scaler.attachToReplayer(tab.replayer, () => controller.activeWindow === tab)
    }
    controller.onWindowChange((onScreen) => {
        for (const tab of windows) {
            tab.root.style.display = tab === onScreen ? '' : 'none'
        }
        scaler.fitReplayer(onScreen.replayer)
    })

    if (config.showMetadataFooter) {
        const footer = new MetadataFooter(windows, segments, firstTimestamp, controller)
        footer.start()
    }

    bridge.publishSegments(segments, firstTimestamp)
    bridge.signalStarted()

    const startOffset = config.startOffsetS != null ? config.startOffsetS * 1000 : 0
    await bridge.waitForStart()
    controller.start(Math.max(0, startOffset))
}

const bridge = new HostBridge()
try {
    const config = bridge.getConfig()
    init(config, bridge).catch((err) => {
        const message = err instanceof Error ? err.message : String(err)
        const retryable = err instanceof DataLoadError ? err.retryable : true
        const code = err instanceof DataLoadError ? 'DATA_LOAD_FAILED' : 'INIT_FAILED'
        bridge.setError({ code, message, retryable })
        bridge.signalEnded()
    })
} catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    bridge.setError({ code: 'INIT_FAILED', message, retryable: true })
    bridge.signalEnded()
}
