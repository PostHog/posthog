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

    const { replayer, segments, firstTimestamp } = setup

    const footerHeight = config.showMetadataFooter ? 32 : 0
    const scaler = new ViewportScaler(contentEl, footerHeight)
    scaler.attachToReplayer(replayer)

    const controller = new PlaybackController(
        replayer,
        segments,
        firstTimestamp,
        {
            skipInactivity: config.skipInactivity,
            endTimestamp: config.endTimestamp,
        },
        bridge
    )

    if (config.showMetadataFooter) {
        const footer = new MetadataFooter(replayer, segments, firstTimestamp, controller, setup.initialURL)
        footer.start()
    }

    bridge.publishSegments(segments, firstTimestamp)
    bridge.signalStarted()

    const startOffset = config.startTimestamp ? config.startTimestamp - setup.events[0].timestamp : 0
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
