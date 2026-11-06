import { Counter } from 'prom-client'

import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { buildIntegerMatcher } from '~/common/config/matchers'
import { logger } from '~/common/utils/logger'

import { HogFunctionType } from '../types'

export type SecretOriginCheckMode = 'off' | 'observe' | 'enforce'

type SecretOriginOutcome = 'allowed' | 'unbound' | 'unbound_missing' | 'mismatch' | 'error'

export type SecretOriginRequest = {
    url: string
    headers: Record<string, string>
    body: string | undefined
    params: Pick<
        CyclotronInvocationQueueParametersFetchType,
        'secret_headers_input' | 'standard_webhooks' | 'aws_sigv4'
    >
}

export type SecretOriginRefusal = { inputKey: string; origin: string }

// A shorter value matches too much unrelated text in a URL, header or body, such as a JSON key or a path segment.
const MIN_SCANNED_SECRET_LENGTH = 8

const WARN_WINDOW_MS = 15 * 60 * 1000
const WARN_MAX_ENTRIES = 10_000

export const secretOriginCheckCounter = new Counter({
    name: 'cdp_secret_origin_check_total',
    help: 'Stored secrets a fetch carries, by whether the request origin is one the secret was saved for',
    labelNames: ['outcome', 'mode'],
})

export function parseSecretOriginCheckMode(value: string | undefined): SecretOriginCheckMode {
    const mode = (value ?? '').trim().toLowerCase()
    return mode === 'off' || mode === 'enforce' ? mode : 'observe'
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * The origin in the format `url_origin` in products/cdp/backend/secret_origins.py stores. It uses the WHATWG parser
 * that the HTTP client uses, so userinfo, letter case and a default port resolve to the host the request goes to.
 */
function requestOrigin(url: string): string | null {
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        return null
    }
    // A loop and not /\.+$/, because that regex backtracks in quadratic time on a long run of dots.
    let end = parsed.hostname.length
    while (end > 0 && parsed.hostname[end - 1] === '.') {
        end--
    }
    const port = parsed.port ? `:${parsed.port}` : ''
    return `${parsed.protocol}//${parsed.hostname.slice(0, end)}${port}`
}

function secretTexts(value: unknown): string[] {
    if (typeof value === 'string') {
        return [value]
    }
    return isRecord(value) ? Object.values(value).filter((entry): entry is string => typeof entry === 'string') : []
}

function namedSecretInputs(params: SecretOriginRequest['params']): Set<string | undefined> {
    return new Set([
        params.secret_headers_input,
        params.standard_webhooks?.secret_input,
        params.aws_sigv4?.access_key_id_input,
        params.aws_sigv4?.secret_access_key_input,
        params.aws_sigv4?.session_token_input,
    ])
}

function originOutcome(allowedOrigins: unknown, origin: string): SecretOriginOutcome {
    if (allowedOrigins === '*') {
        return 'unbound'
    }
    if (!Array.isArray(allowedOrigins)) {
        return 'unbound_missing'
    }
    return allowedOrigins.includes(origin) ? 'allowed' : 'mismatch'
}

function carriedSecretOutcomes(
    hogFunction: Pick<HogFunctionType, 'encrypted_inputs'>,
    request: SecretOriginRequest
): { origin: string; outcomes: { inputKey: string; outcome: SecretOriginOutcome }[] } | null {
    // encrypted_inputs stays a ciphertext string when decryption fails, and its entries come from stored JSON.
    const encryptedInputs: unknown = hogFunction.encrypted_inputs
    const origin = requestOrigin(request.url)
    if (!isRecord(encryptedInputs) || !origin) {
        return null
    }

    const named = namedSecretInputs(request.params)
    const sentTexts = [request.url, ...Object.values(request.headers), request.body ?? '']
    const outcomes: { inputKey: string; outcome: SecretOriginOutcome }[] = []
    for (const [inputKey, input] of Object.entries(encryptedInputs)) {
        if (!isRecord(input)) {
            continue
        }
        const carried =
            named.has(inputKey) ||
            secretTexts(input.value).some(
                (secret) =>
                    secret.length >= MIN_SCANNED_SECRET_LENGTH &&
                    sentTexts.some((text) => typeof text === 'string' && text.includes(secret))
            )
        if (carried) {
            outcomes.push({ inputKey, outcome: originOutcome(input.allowed_origins, origin) })
        }
    }
    return { origin, outcomes }
}

// Fails open on an internal error in every mode, because a refused request is a lost delivery.
export class SecretOriginGuard {
    private readonly enforcedForTeam: (teamId: number) => boolean
    private readonly lastWarnedAt = new Map<string, number>()

    constructor(
        private readonly mode: SecretOriginCheckMode,
        enforceTeams: string | undefined
    ) {
        this.enforcedForTeam = buildIntegerMatcher(enforceTeams, true)
    }

    check(
        hogFunction: Pick<HogFunctionType, 'id' | 'team_id' | 'template_id' | 'encrypted_inputs'>,
        request: SecretOriginRequest
    ): SecretOriginRefusal | null {
        if (this.mode === 'off') {
            return null
        }
        const mode = this.mode === 'enforce' && this.enforcedForTeam(hogFunction.team_id) ? 'enforce' : 'observe'
        try {
            const result = carriedSecretOutcomes(hogFunction, request)
            let refusal: SecretOriginRefusal | null = null
            for (const { inputKey, outcome } of result?.outcomes ?? []) {
                secretOriginCheckCounter.inc({ outcome, mode })
                if (outcome === 'mismatch' && result) {
                    this.warn(hogFunction, inputKey, result.origin, mode)
                    refusal ??= { inputKey, origin: result.origin }
                }
            }
            return mode === 'enforce' ? refusal : null
        } catch (error) {
            secretOriginCheckCounter.inc({ outcome: 'error', mode })
            logger.warn('🦔', '[HogExecutor] Secret origin check skipped due to an internal error', {
                error: error instanceof Error ? error.message : String(error),
                teamId: hogFunction.team_id,
                functionId: hogFunction.id,
            })
            return null
        }
    }

    // One line per function, input and origin in the window, because a destination sends on every matching event.
    private warn(
        hogFunction: Pick<HogFunctionType, 'id' | 'team_id' | 'template_id'>,
        inputKey: string,
        origin: string,
        mode: SecretOriginCheckMode
    ): void {
        const key = `${hogFunction.id}:${inputKey}:${origin}`
        const now = Date.now()
        const warnedAt = this.lastWarnedAt.get(key)
        if (warnedAt !== undefined && now - warnedAt < WARN_WINDOW_MS) {
            return
        }
        this.lastWarnedAt.delete(key)
        this.lastWarnedAt.set(key, now)
        if (this.lastWarnedAt.size > WARN_MAX_ENTRIES) {
            this.lastWarnedAt.delete(this.lastWarnedAt.keys().next().value!)
        }
        logger.warn('🦔', '[HogExecutor] Secret input sent to an origin it was not saved for', {
            teamId: hogFunction.team_id,
            functionId: hogFunction.id,
            templateId: hogFunction.template_id,
            inputKey,
            origin,
            mode,
        })
    }
}
