export const EXIT_SUCCESS = 0
export const EXIT_FAILURE = 1
export const EXIT_USAGE = 2
export const EXIT_NEEDS_PERSON = 3
export const EXIT_PENDING = 4

// Ctrl-C. Shells report 130 for a process that SIGINT stopped, so hog uses the same code.
export const EXIT_CANCELLED = 130

export interface ExitCodeEntry {
    code: number
    meaning: string
    // --no-fail turns the code into EXIT_SUCCESS, so a build never breaks on hog. A usage error and
    // Ctrl-C keep their codes, because the command never ran as written.
    noFail: boolean
}

export const EXIT_CODES: readonly ExitCodeEntry[] = [
    { code: EXIT_SUCCESS, meaning: 'The command worked', noFail: false },
    {
        code: EXIT_FAILURE,
        meaning: 'The command failed, or a check found problems, such as drift in `hog endpoints diff`',
        noFail: true,
    },
    {
        code: EXIT_USAGE,
        meaning: 'A usage error, such as an unknown command or a missing or invalid option',
        noFail: false,
    },
    {
        code: EXIT_NEEDS_PERSON,
        meaning:
            'A person has to act before the command can go on, such as logging in, approving in the browser or answering a question. The hint or the output says what',
        noFail: true,
    },
    {
        code: EXIT_PENDING,
        meaning: 'The work started and is still running. The output names the `--wait` command that resumes it',
        noFail: true,
    },
    { code: EXIT_CANCELLED, meaning: 'Cancelled with Ctrl-C at a prompt', noFail: false },
]

export const NO_FAIL_CODES: readonly number[] = EXIT_CODES.filter((entry) => entry.noFail).map((entry) => entry.code)
export const KEPT_ON_NO_FAIL_CODES: readonly number[] = EXIT_CODES.filter(
    (entry) => !entry.noFail && entry.code !== EXIT_SUCCESS
).map((entry) => entry.code)

// The error codes that mean a person has to act wherever hog throws them. Every other code exits
// with EXIT_FAILURE unless the throw site passes another exit code.
const EXIT_CODE_BY_ERROR: Readonly<Record<string, number>> = {
    not_authenticated: EXIT_NEEDS_PERSON,
    session_expired: EXIT_NEEDS_PERSON,
    step_up_required: EXIT_NEEDS_PERSON,
    step_up_unavailable: EXIT_NEEDS_PERSON,
    step_up_other_project: EXIT_NEEDS_PERSON,
    scopes_not_granted: EXIT_NEEDS_PERSON,
    region_required: EXIT_NEEDS_PERSON,
    login_needs_a_person: EXIT_NEEDS_PERSON,
    not_in_ci: EXIT_NEEDS_PERSON,
    keychain_access_denied: EXIT_NEEDS_PERSON,
    keychain_access_timeout: EXIT_NEEDS_PERSON,
    workload_no_matching_policy: EXIT_NEEDS_PERSON,
    workload_policy_request_pending: EXIT_NEEDS_PERSON,
}

export function exitCodeFor(code: string): number {
    return Object.hasOwn(EXIT_CODE_BY_ERROR, code) ? EXIT_CODE_BY_ERROR[code]! : EXIT_FAILURE
}

export interface ErrorPatch {
    message?: string
    hint?: string
}

// A failure hog reports to the caller. `code` is stable and machine-readable, so agents and
// scripts can branch on it; `message` and `hint` are for people. Agents also get `details`.
// `serverDetail` is PostHog's own reason for refusing a request. It stays out of `message`, because
// it can repeat values from the request, and `Output` shows it only outside CI, where logs can be public.
export class HogError extends Error {
    constructor(
        readonly code: string,
        message: string,
        readonly hint?: string,
        readonly exitCode: number = exitCodeFor(code),
        readonly details?: Readonly<Record<string, unknown>>,
        readonly serverDetail?: string
    ) {
        super(message)
        this.name = 'HogError'
    }

    withHint(hint: string): HogError {
        return this.copy({ hint })
    }

    withMessage(message: string): HogError {
        return this.copy({ message })
    }

    protected copy(patch: ErrorPatch): HogError {
        return new HogError(
            this.code,
            patch.message ?? this.message,
            patch.hint ?? this.hint,
            this.exitCode,
            this.details,
            this.serverDetail
        )
    }
}

export function wrapFailure(code: string, context: string, cause: unknown, hint?: string): HogError {
    const message = cause instanceof Error ? cause.message : String(cause)
    // A cause with its own exit code, such as a revoked login that needs a person, keeps its code, hint,
    // details and exit code, because they say what has to happen next. The context only goes in front.
    if (cause instanceof HogError && cause.exitCode !== EXIT_FAILURE) {
        return cause.withMessage(`${context}: ${message}`)
    }
    const serverDetail = cause instanceof HogError ? cause.serverDetail : undefined
    return new HogError(code, `${context}: ${message}`, hint, EXIT_FAILURE, undefined, serverDetail)
}

export const SERVER_DETAIL_HIDDEN = "PostHog's reason is hidden in CI. Run the command outside CI to see it."

export function withServerDetail(message: string, serverDetail: string): string {
    return `${message.replace(/\.$/, '')}: ${serverDetail}`
}

// The text of a failure that a command keeps in its result instead of throwing, such as one endpoint
// of a push. Outside CI it ends with PostHog's reason. In CI it says where to see the reason instead.
export function failureText(error: unknown, isCI: boolean): string {
    const message = error instanceof Error ? error.message : String(error)
    const serverDetail = error instanceof HogError ? error.serverDetail : undefined
    if (serverDetail === undefined) {
        return message
    }
    return isCI ? `${message} ${SERVER_DETAIL_HIDDEN}` : withServerDetail(message, serverDetail)
}

const EXIT_CODE_BY_STATUS: Readonly<Record<string, number>> = {
    pending: EXIT_NEEDS_PERSON,
    running: EXIT_PENDING,
}

// For commands whose result says in `status` that it waits for a person (`pending`) or for PostHog
// (`running`). Opt-in, because results that pass PostHog objects through can carry the same words.
export function waitingExitCode<Result extends { status: string }>(result: Result): number {
    return Object.hasOwn(EXIT_CODE_BY_STATUS, result.status) ? EXIT_CODE_BY_STATUS[result.status]! : EXIT_SUCCESS
}
