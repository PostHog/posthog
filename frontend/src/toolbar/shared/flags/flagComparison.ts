import type { PostHog } from 'posthog-js'

import { isInToolbarRoot } from '~/toolbar/shared/utils'
import { captureElementScreenshot } from '~/toolbar/shared/utils/screenshot'

import type { FlagInfo } from './flagInfo'

const SETTLE_QUIET_MS = 1000
const SETTLE_MAX_MS = 8000

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

export async function capturePage(): Promise<PageCapture> {
    const root = document.documentElement
    const width = root.clientWidth
    const height = root.scrollHeight
    const blob = await captureElementScreenshot(root, { pixelRatio: 1, width, height })
    return { blob, width, height }
}

export async function imagesMatch(first: Blob, second: Blob): Promise<boolean> {
    if (first.size !== second.size) {
        return false
    }
    const [a, b] = await Promise.all([first, second].map(async (blob) => new Uint8Array(await blob.arrayBuffer())))
    return a.every((byte, index) => byte === b[index])
}
