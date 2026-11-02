import { BeforeSendFn } from 'posthog-js'

import { UNACTIONABLE_NETWORK_ERROR_MESSAGES, isScopeNotFoundMessage } from 'lib/api-error'

/** One entry of the `$exception_list` that posthog-js builds, reduced to the fields these filters read. */
interface CapturedException {
    type?: string
    value?: string
    mechanism?: { handled?: boolean }
    stacktrace?: { frames?: unknown[] }
}

/**
 * Builds a `before_send` filter that drops an `$exception` event when `isNoise` matches its exception
 * list. posthog-js appends each wrapped `cause` to that list, so a filter that reads only the first
 * entry misses an expected error that a caller rethrew inside another one.
 */
function dropExceptionsWhen(isNoise: (exceptions: CapturedException[]) => boolean): BeforeSendFn {
    return (event) => {
        if (event?.event !== '$exception') {
            return event
        }
        const exceptions: CapturedException[] = event.properties?.$exception_list ?? []
        return isNoise(exceptions) ? null : event
    }
}

/**
 * Drops an uncaught rejection from a request on a deleted or inaccessible project or organization.
 * The kea loaders and `shouldReportApiFailure` already excuse this failure, but a promise that no
 * caller handles reaches error tracking through autocapture and skips those checks.
 */
export const dropScopeNotFoundExceptions = dropExceptionsWhen((exceptions) =>
    exceptions.some((exception) => isScopeNotFoundMessage(exception?.value))
)

/**
 * The `detail` messages the backend sends with the three handled auth-gate 403s. Keep in sync with:
 *
 *   two_factor_setup_required        - posthog/helpers/two_factor_session.py
 *   two_factor_verification_required - posthog/helpers/two_factor_session.py
 *   sensitive_action_required_reauth - posthog/permissions.py (TimeSensitiveActionPermission)
 */
const HANDLED_AUTH_GATE_MESSAGES: ReadonlySet<string> = new Set([
    '2FA setup required',
    '2FA verification required',
    'This action requires you to be recently authenticated.',
])

/**
 * Drops a handled auth gate. `apiStatusLogic` turns these 403s into the 2FA setup or verify flow or a
 * re-auth prompt, so a rejected request is expected control flow, not a crash. `$exception_list`
 * keeps only the error type, message and stack, and the DRF `code` never reaches `before_send`, so
 * the match is on the message, which `ApiError` sets from the response `detail`.
 */
export const dropHandledAuthGateExceptions = dropExceptionsWhen((exceptions) =>
    exceptions.some((exception) => exception?.value != null && HANDLED_AUTH_GATE_MESSAGES.has(exception.value))
)

/**
 * Drops a request the browser never sent because the client was offline or the document was being
 * torn down. Neither is a defect, and both arrive as unhandled rejections from whichever logic was
 * fetching, so each one fingerprints against a different stack and files its own issue. A
 * `NetworkError` with reason `network` is kept on purpose: a request that failed while the user was
 * online and staying put is worth seeing.
 */
export const dropUnactionableNetworkExceptions = dropExceptionsWhen((exceptions) =>
    exceptions.some(
        (exception) =>
            exception?.type === 'NetworkError' &&
            exception.value != null &&
            UNACTIONABLE_NETWORK_ERROR_MESSAGES.has(exception.value)
    )
)

/**
 * Browser engines word an unknown-identifier ReferenceError in one of two ways: WebKit says "Can't
 * find variable: X", V8 and SpiderMonkey say "X is not defined". Both name a single identifier. Our
 * own bundle never leaves such an identifier undefined at runtime.
 */
const UNKNOWN_IDENTIFIER_REFERENCE_ERROR = /^(Can't find variable: \S+|\S+ is not defined)$/

/**
 * Drops a ReferenceError that a browser extension or an in-app browser injected into the page, for an
 * identifier our code never defines. posthog-js captures it through the global handler with no stack
 * frames, because the throwing script is not ours. A real ReferenceError in our own bundle carries a
 * stack, so the empty-stack check keeps those. Each injected variant fingerprints to its own issue,
 * so the whole class is dropped here.
 */
export const dropInjectedScriptReferenceErrors = dropExceptionsWhen(
    (exceptions) =>
        !exceptions.some((exception) => (exception?.stacktrace?.frames?.length ?? 0) > 0) &&
        exceptions.every((exception) => exception?.mechanism?.handled === false) &&
        exceptions.some(
            (exception) =>
                exception?.type === 'ReferenceError' &&
                exception.value != null &&
                UNKNOWN_IDENTIFIER_REFERENCE_ERROR.test(exception.value)
        )
)
