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
            endOffsetS: config.endOffsetS,
        },
        bridge
    )

    if (config.showMetadataFooter) {
        const footer = new MetadataFooter(replayer, segments, firstTimestamp, controller, setup.initialURL)
        footer.start()
    }

    bridge.publishSegments(segments, firstTimestamp)
    bridge.signalStarted()

    const startOffset = config.startOffsetS != null ? config.startOffsetS * 1000 : 0
    await bridge.waitForStart()
    controller.start(Math.max(0, startOffset))
}

function describeError(err: unknown): { message: string; stack?: string } {
    return err instanceof Error ? { message: err.message, stack: err.stack } : { message: String(err) }
}

const bridge = new HostBridge()
try {
    const config = bridge.getConfig()
    init(config, bridge).catch((err) => {
        const retryable = err instanceof DataLoadError ? err.retryable : true
        const code = err instanceof DataLoadError ? 'DATA_LOAD_FAILED' : 'INIT_FAILED'
        bridge.setError({ code, retryable, ...describeError(err) })
        bridge.signalEnded()
    })
} catch (err) {
    bridge.setError({ code: 'INIT_FAILED', retryable: true, ...describeError(err) })
    bridge.signalEnded()
}
