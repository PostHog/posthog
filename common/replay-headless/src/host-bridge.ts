import type { RecordingSegment } from '@posthog/replay-shared'

import { PLAYER_EMIT_FN, PLAYER_INIT_EVENT, PLAYER_START_EVENT } from './protocol'
import type { PlayerConfig, PlayerError, PlayerMessage } from './protocol'

/**
 * Player-side counterpart to the rasterizer's PlayerController.
 *
 * Sends messages to the host process (Puppeteer) via an exposed function
 * callback, and receives commands via DOM events. All player → rasterizer
 * communication goes through {@link emit} so the protocol is defined in
 * one place.
 */
export class HostBridge {
    // --- Emit ---

    private emit(msg: PlayerMessage): void {
        const fn = window[PLAYER_EMIT_FN]
        if (typeof fn === 'function') {
            void fn(msg)
        }
    }

    // --- Signals ---

    signalStarted(): void {
        this.emit({ type: 'started' })
    }

    signalEnded(): void {
        this.emit({ type: 'ended' })
    }

    setError(error: PlayerError): void {
        this.emit({ type: 'error', ...error })
    }

    reportLoadingProgress(loaded: number, total: number): void {
        this.emit({ type: 'loading_progress', loaded, total })
    }

    // --- Data ---

    publishSegments(segments: RecordingSegment[], firstTimestamp: number): void {
        const periods = segments.map((seg) => ({
            ts_from_s: Math.round(seg.startTimestamp - firstTimestamp) / 1000,
            ts_to_s: Math.round(seg.endTimestamp - firstTimestamp) / 1000,
            active: seg.isActive,
        }))
        this.emit({ type: 'inactivity_periods', periods })
    }

    // --- Events ---

    /**
     * Signal to the rasterizer that the player is ready to receive config.
     * The rasterizer responds by dispatching a CustomEvent with the config
     * as its detail payload.
     */
    async waitForConfig(timeoutMs = 30000): Promise<PlayerConfig> {
        const configPromise = new Promise<PlayerConfig>((resolve, reject) => {
            const timer = setTimeout(
                () => reject(new Error(`${PLAYER_INIT_EVENT} not received within ${timeoutMs / 1000}s`)),
                timeoutMs
            )
            window.addEventListener(
                PLAYER_INIT_EVENT,
                ((event: CustomEvent<PlayerConfig>) => {
                    clearTimeout(timer)
                    resolve(event.detail)
                }) as EventListener,
                { once: true }
            )
        })

        this.emit({ type: 'ready' })
        return configPromise
    }

    async waitForStart(timeoutMs = 30000): Promise<void> {
        await new Promise<void>((resolve, reject) => {
            const timer = setTimeout(
                () => reject(new Error(`${PLAYER_START_EVENT} not received within ${timeoutMs / 1000}s`)),
                timeoutMs
            )
            window.addEventListener(
                PLAYER_START_EVENT,
                () => {
                    clearTimeout(timer)
                    resolve()
                },
                { once: true }
            )
        })
    }
}
