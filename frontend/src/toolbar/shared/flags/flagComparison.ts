import type { PostHog } from 'posthog-js'

import { withTimeout } from 'lib/utils/async'

import { isInToolbarRoot } from '~/toolbar/shared/utils'
import { captureElementScreenshot } from '~/toolbar/shared/utils/screenshot'

import { CaptureStillRunningError } from './flagComparisonErrors'

const SETTLE_QUIET_MS = 1000
const SETTLE_MAX_MS = 8000
const CAPTURE_MAX_MS = 20000

export type FlagOverrides = Record<string, string | boolean>

export function readFlagOverrides(posthog: PostHog): FlagOverrides | null {
    return posthog.get_property('$override_feature_flags') ?? null
}

/** Leaves payload overrides alone. posthog-js fires the page's `onFeatureFlags` callbacks synchronously, so no flag reload is needed. */
export function writeFlagOverrides(posthog: PostHog, flags: FlagOverrides | null): void {
    posthog.featureFlags.overrideFeatureFlags({ flags: flags ?? false })
}

function isToolbarMutation(mutation: MutationRecord): boolean {
    const element = mutation.target instanceof HTMLElement ? mutation.target : mutation.target.parentElement
    return !!element && isInToolbarRoot(element)
}

export function waitForPageToSettle(quietMs: number = SETTLE_QUIET_MS, maxMs: number = SETTLE_MAX_MS): Promise<void> {
    return new Promise((resolve) => {
        let quietTimer: ReturnType<typeof setTimeout> | undefined
        let maxTimer: ReturnType<typeof setTimeout> | undefined
        const observer = new MutationObserver((mutations) => {
            if (mutations.some((mutation) => !isToolbarMutation(mutation))) {
                restartQuietTimer()
            }
        })
        const finish = (): void => {
            observer.disconnect()
            clearTimeout(quietTimer)
            clearTimeout(maxTimer)
            resolve()
        }
        const restartQuietTimer = (): void => {
            clearTimeout(quietTimer)
            quietTimer = setTimeout(finish, quietMs)
        }

        observer.observe(document.documentElement, {
            subtree: true,
            childList: true,
            attributes: true,
            characterData: true,
        })
        maxTimer = setTimeout(finish, maxMs)
        restartQuietTimer()
    })
}

export interface PageCapture {
    blob: Blob
    width: number
    height: number
}

// html-to-image cannot cancel a capture, so one that timed out keeps running.
// A new capture throws until that one ends, so the page is never cloned twice at once.
let runningCapture: Promise<Blob> | null = null

export function isCaptureRunning(): boolean {
    return runningCapture !== null
}

/** Rejects after `maxMs`, because a stalled image load or a paused `requestAnimationFrame` would keep the comparison's overrides on the page. */
export async function capturePage(maxMs: number = CAPTURE_MAX_MS): Promise<PageCapture> {
    if (runningCapture) {
        throw new CaptureStillRunningError()
    }
    const root = document.documentElement
    const width = root.clientWidth
    const height = root.scrollHeight
    const capture = captureElementScreenshot(root, { pixelRatio: 1, width, height })
    runningCapture = capture
    const clearRunningCapture = (): void => {
        if (runningCapture === capture) {
            runningCapture = null
        }
    }
    capture.then(clearRunningCapture, clearRunningCapture)
    const blob = await withTimeout(capture, maxMs, `The page capture took longer than ${maxMs} ms`)
    return { blob, width, height }
}

export async function imagesMatch(first: Blob, second: Blob): Promise<boolean> {
    if (first.size !== second.size) {
        return false
    }
    const [a, b] = await Promise.all([first, second].map(async (blob) => new Uint8Array(await blob.arrayBuffer())))
    return a.every((byte, index) => byte === b[index])
}
