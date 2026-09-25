import { DataLoadError } from './data-loader'
import { HostBridge } from './host-bridge'
import { MetadataFooter } from './metadata-footer'
import { PlaybackController } from './playback-controller'
import { createReplayer } from './replayer-factory'
import type { PlayerConfig } from './types'
import { ViewportScaler } from './viewport-scaler'

async function init(config: PlayerConfig, bridge: HostBridge): Promise<void> {
    const contentEl = document.querySelector('.PlayerFrame__content') as HTMLElement

    const setup = await createReplayer(config, contentEl, bridge)
    if (!setup) {
        bridge.setError({
            code: 'NO_SNAPSHOTS',
            message: 'No snapshots after processing',
            retryable: true,
        })
        bridge.signalEnded()
        return
    }

    const { windows, segments, firstTimestamp } = setup

    const footerHeight = config.showMetadataFooter ? 32 : 0
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
