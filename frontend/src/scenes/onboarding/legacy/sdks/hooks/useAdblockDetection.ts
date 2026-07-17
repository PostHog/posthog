import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

export type AdblockDetectionResult = 'unknown' | 'blocked' | 'ok'

/**
 * Detects whether PostHog requests are being blocked (e.g. by an adblocker).
 *
 * Two checks are performed:
 *  1. `window.posthog?.__loaded` – if posthog-js failed to initialize the
 *     property will be falsy.
 *  2. A lightweight fetch to the PostHog ingestion `/decide/` endpoint – a
 *     network error (not an HTTP error) strongly suggests the request was
 *     blocked.
 *
 * The result is only surfaced after `delayMs` (default 20 s) so we don't
 * flash a warning before the user has had time to wait.
 */
export function useAdblockDetection(delayMs: number = 20_000): AdblockDetectionResult {
    const [result, setResult] = useState<AdblockDetectionResult>('unknown')
    const detectionDone = useRef(false)

    useEffect(() => {
        let cancelled = false

        const detect = async (): Promise<AdblockDetectionResult> => {
            // Check 1 – posthog-js loaded flag
            const ph = (window as any).posthog
            if (ph && !ph.__loaded) {
                return 'blocked'
            }

            // Check 2 – attempt a fetch to the ingestion endpoint
            try {
                await fetch('https://us.i.posthog.com/decide/?v=3', {
                    method: 'POST',
                    mode: 'no-cors',
                    body: JSON.stringify({}),
                })
                // If fetch resolves (even opaque response) → not blocked
                return 'ok'
            } catch {
                // Network error → blocked
                return 'blocked'
            }
        }

        const timer = setTimeout(() => {
            if (cancelled || detectionDone.current) {
                return
            }
            detect()
                .then((r) => {
                    if (!cancelled) {
                        detectionDone.current = true
                        setResult(r)
                        posthog.capture('onboarding adblock detection completed', { status: r })
                    }
                })
                .catch(() => {
                    if (!cancelled) {
                        detectionDone.current = true
                        setResult('blocked')
                        posthog.capture('onboarding adblock detection completed', { status: 'blocked' })
                    }
                })
        }, delayMs)

        return () => {
            cancelled = true
            clearTimeout(timer)
        }
    }, [delayMs])

    return result
}
