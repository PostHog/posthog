import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { setReadOnlyGetter, setReadOnlyNotifier } from 'lib/readOnlyGuard'

import type { selfReadOnlyModeLogicType } from './selfReadOnlyModeLogicType'

export const ESCALATION_OPTIONS = [
    { seconds: 30, label: 'Allow for 30s' },
    { seconds: 300, label: 'Allow for 5 min' },
] as const

export const selfReadOnlyModeLogic = kea<selfReadOnlyModeLogicType>([
    path(['layout', 'navigation', 'SelfReadOnlyNotice', 'selfReadOnlyModeLogic']),

    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        escalate: (durationSeconds: number) => ({ durationSeconds }),
        endEscalation: true,
        notifyBlocked: (method: string) => ({ method }),
    }),

    reducers({
        escalatedUntil: [
            null as number | null,
            {
                escalate: (_, { durationSeconds }) => Date.now() + durationSeconds * 1000,
                endEscalation: () => null,
            },
        ],
    }),

    selectors({
        isFlagEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.READ_ONLY_MODE],
        ],
        // isEscalated reads Date.now() inside a selector — selectors aren't time-reactive.
        // It only flips back to false when escalatedUntil is reset by the setTimeout in the
        // `escalate` listener firing `endEscalation`. Acceptable: the timer runs even on
        // hidden tabs (pauseOnPageHidden: false).
        isEscalated: [(s) => [s.escalatedUntil], (until): boolean => until !== null && until > Date.now()],
        isReadOnly: [
            (s) => [s.isFlagEnabled, s.isEscalated],
            (isFlagEnabled, isEscalated): boolean => isFlagEnabled && !isEscalated,
        ],
    }),

    listeners(({ actions, cache }) => ({
        escalate: ({ durationSeconds }) => {
            cache.disposables.add(
                () => {
                    const id = setTimeout(() => actions.endEscalation(), durationSeconds * 1000)
                    return () => clearTimeout(id)
                },
                'escalationTimer',
                { pauseOnPageHidden: false }
            )
            posthog.capture?.('read_only_escalated', { duration_seconds: durationSeconds })
        },
        endEscalation: () => {
            cache.disposables.dispose('escalationTimer')
            lemonToast.info('Back to read-only mode.', { toastId: 'read-only-resumed' })
            posthog.capture?.('read_only_ended')
        },
        // Analytics-only — the user-visible toast is no longer fired here. Catch blocks
        // that match `e instanceof ApiError` already surface `ReadOnlyModeError.detail`.
        notifyBlocked: ({ method }) => {
            posthog.capture?.('read_only_write_blocked', { method })
        },
    })),

    afterMount(({ actions }) => {
        // Read via `findMounted()` rather than capturing the `values` proxy:
        // the store path can be torn down (HMR, logout, kea resetContext) without
        // our `beforeUnmount` clearing the getter, which would throw a kea
        // "path not in store" error on the next mutation.
        setReadOnlyGetter(() => selfReadOnlyModeLogic.findMounted()?.values.isReadOnly ?? false)
        setReadOnlyNotifier((method) => actions.notifyBlocked(method))

        // The error-tracking filter that drops ReadOnlyModeError `$exception`
        // events (`dropReadOnlyExceptions`) is installed centrally at posthog
        // init in `loadPostHogJS`, so it applies for the whole app lifetime and
        // is not clobbered by this logic mounting/unmounting.

        // The user-facing toast for blocked writes is shown by the standard
        // `e instanceof ApiError → lemonToast.error(e.detail)` pattern that
        // every write call-site already implements. ReadOnlyModeError extends
        // ApiError and carries a method-specific `detail`, so no extra hook
        // is needed.
    }),

    beforeUnmount(() => {
        setReadOnlyGetter(null)
        setReadOnlyNotifier(null)
    }),
])
