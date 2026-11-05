import type { PostHog } from 'posthog-js'

import { isInToolbarRoot } from '~/toolbar/shared/utils'
import { captureElementScreenshot } from '~/toolbar/shared/utils/screenshot'

import type { FlagInfo } from './flagInfo'

const SETTLE_QUIET_MS = 1000
const SETTLE_MAX_MS = 8000
const CAPTURE_MAX_MS = 20000

export interface ComparisonState {
    value: string | boolean
    label: string
}

/** Off comes first, so it is the "before" image. Then on, or each variant of a multivariate flag. */
export function comparisonStates(flag: FlagInfo): ComparisonState[] {
    const off: ComparisonState = { value: false, label: 'Off' }
    if (flag.variants.length === 0) {
        return [off, { value: true, label: 'On' }]
    }
    return [off, ...flag.variants.map((variant) => ({ value: variant.key, label: variant.key }))]
}

export type FlagOverrides = Record<string, string | boolean>

export class FlagOverridesChangedError extends Error {
    constructor() {
        super('The flag overrides changed during the comparison')
        this.name = 'FlagOverridesChangedError'
    }
}

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

// html-to-image cannot cancel a capture, so one that timed out keeps running. A new capture waits for it to end instead of piling up a second clone of the page.
let runningCapture: Promise<Blob> | null = null

/** Rejects after `maxMs`, because a stalled image load or a paused `requestAnimationFrame` would keep the comparison's overrides on the page. */
export async function capturePage(maxMs: number = CAPTURE_MAX_MS): Promise<PageCapture> {
    if (runningCapture) {
        throw new Error('An earlier page capture is still running')
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
    let deadline: ReturnType<typeof setTimeout> | undefined
    try {
        const blob = await Promise.race([
            capture,
            new Promise<never>((_, reject) => {
                deadline = setTimeout(() => reject(new Error(`The page capture took longer than ${maxMs} ms`)), maxMs)
            }),
        ])
        return { blob, width, height }
    } finally {
        clearTimeout(deadline)
    }
}

export async function imagesMatch(first: Blob, second: Blob): Promise<boolean> {
    if (first.size !== second.size) {
        return false
    }
    const [a, b] = await Promise.all([first, second].map(async (blob) => new Uint8Array(await blob.arrayBuffer())))
    return a.every((byte, index) => byte === b[index])
}
