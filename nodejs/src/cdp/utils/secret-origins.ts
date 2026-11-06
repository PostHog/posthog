import { LRUCache } from 'lru-cache'
import { Counter } from 'prom-client'

import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { buildIntegerMatcher } from '~/common/config/matchers'
import { logger } from '~/common/utils/logger'

import { HogFunctionInputSchemaType, HogFunctionType } from '../types'

type SecretOriginCheckMode = 'observe' | 'enforce'

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

export type SecretOriginCheck = {
    mode: SecretOriginCheckMode
    outcomes: SecretOriginOutcome[]
    refusal: SecretOriginRefusal | null
}

type CarriedSecret = { inputKey: string; origin: string; outcome: SecretOriginOutcome }

type CheckedHogFunction = Pick<
    HogFunctionType,
    'id' | 'team_id' | 'template_id' | 'bytecode' | 'inputs' | 'inputs_schema' | 'mappings' | 'encrypted_inputs'
>

// A shorter value matches too much unrelated text in a URL, header or body, such as a JSON key or a path segment.
const MIN_SCANNED_SECRET_LENGTH = 8

export const secretOriginCheckCounter = new Counter({
    name: 'cdp_secret_origin_check_total',
    help: 'Stored secrets the first attempt of a fetch carries, by whether the request origin is one the secret was saved for. Functions whose secrets all predate stored origins are not counted.',
    labelNames: ['outcome', 'mode'],
})

export function countSecretOriginCheck({ mode, outcomes }: SecretOriginCheck): void {
    for (const outcome of outcomes) {
        secretOriginCheckCounter.inc({ outcome, mode })
    }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * The origin in the format `url_origin` in products/cdp/backend/secret_origins.py stores. It uses the WHATWG parser
 * that the HTTP client uses, so userinfo, letter case and a default port resolve to the host the request goes to.
 */
export function requestOrigin(url: string): string | null {
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

function namedSecretInputs(params: SecretOriginRequest['params']): Set<string | undefined> {
    return new Set([
        params.secret_headers_input,
        params.standard_webhooks?.secret_input,
        params.aws_sigv4?.access_key_id_input,
        params.aws_sigv4?.secret_access_key_input,
        params.aws_sigv4?.session_token_input,
    ])
}

function textLeaves(value: unknown): string[] {
    if (typeof value === 'string') {
        return [value]
    }
    if (Array.isArray(value)) {
        return value.flatMap(textLeaves)
    }
    return isRecord(value) ? Object.values(value).flatMap(textLeaves) : []
}

function inputTexts(
    inputs: Record<string, unknown> | null | undefined,
    schema: HogFunctionInputSchemaType[] | undefined
): string[] {
    // A secret saved before inputs were encrypted still sits in plain `inputs`, so it is not a public value.
    const secretKeys = new Set((schema ?? []).filter((field) => field.secret).map((field) => field.key))
    return Object.entries(inputs ?? {})
        .filter(([key]) => !secretKeys.has(key))
        .flatMap(([, input]) => textLeaves(isRecord(input) ? input.value : null))
}

function publicTexts(hogFunction: CheckedHogFunction): Set<string> {
    return new Set([
        ...textLeaves(hogFunction.bytecode),
        ...inputTexts(hogFunction.inputs, hogFunction.inputs_schema),
        ...(hogFunction.mappings ?? []).flatMap((mapping) => inputTexts(mapping.inputs, mapping.inputs_schema)),
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

function carriedSecrets(hogFunction: CheckedHogFunction, request: SecretOriginRequest): CarriedSecret[] {
    // encrypted_inputs stays a ciphertext string when decryption fails, and its entries come from stored JSON.
    const encryptedInputs: unknown = hogFunction.encrypted_inputs
    if (!isRecord(encryptedInputs)) {
        return []
    }
    // A function whose secrets all predate stored origins can never be refused, so it skips the scan.
    const hasStoredOrigins = Object.values(encryptedInputs).some(
        (input) => isRecord(input) && input.allowed_origins !== undefined
    )
    const origin = hasStoredOrigins ? requestOrigin(request.url) : null
    if (!origin) {
        return []
    }

    const named = namedSecretInputs(request.params)
    // A value the function also holds in its hog code or in a plain input of the function or of a mapping, such as
    // `application/json` in both the plain and the secret headers, is not secret, and sending it to another origin
    // leaks nothing. Without this, an enforced team could not send such a value to a second origin at all.
    const knownTexts = publicTexts(hogFunction)
    const sentTexts = [request.url, ...Object.values(request.headers), request.body ?? '']
    const isSent = (secret: string): boolean =>
        secret.length >= MIN_SCANNED_SECRET_LENGTH &&
        !knownTexts.has(secret) &&
        sentTexts.some((text) => typeof text === 'string' && text.includes(secret))

    const carried: CarriedSecret[] = []
    for (const [inputKey, input] of Object.entries(encryptedInputs)) {
        if (!isRecord(input)) {
            continue
        }
        if (named.has(inputKey) || textLeaves(input.value).some(isSent)) {
            carried.push({ inputKey, origin, outcome: originOutcome(input.allowed_origins, origin) })
        }
    }
    return carried
}

// Fails open on an internal error, because a refused request is a lost delivery.
export class SecretOriginGuard {
    private readonly observedForTeam: (teamId: number) => boolean
    private readonly enforcedForTeam: (teamId: number) => boolean
    // One line per function, input and origin in the window, because a destination sends on every matching event.
    private readonly warned = new LRUCache<string, true>({ max: 10_000, ttl: 15 * 60 * 1000 })

    constructor({ observeTeams, enforceTeams }: { observeTeams: string; enforceTeams: string }) {
        this.observedForTeam = buildIntegerMatcher(observeTeams.trim(), true)
        this.enforcedForTeam = buildIntegerMatcher(enforceTeams.trim(), true)
    }

    check(hogFunction: CheckedHogFunction, request: SecretOriginRequest): SecretOriginCheck {
        const enforced = this.enforcedForTeam(hogFunction.team_id)
        if (!enforced && !this.observedForTeam(hogFunction.team_id)) {
            return { mode: 'observe', outcomes: [], refusal: null }
        }
        const mode = enforced ? 'enforce' : 'observe'
        try {
            const carried = carriedSecrets(hogFunction, request)
            const mismatches = carried.filter(({ outcome }) => outcome === 'mismatch')
            for (const { inputKey, origin } of mismatches) {
                this.warn(hogFunction, inputKey, origin, mode)
            }
            const [refused] = mismatches
            return {
                mode,
                outcomes: carried.map(({ outcome }) => outcome),
                refusal: mode === 'enforce' && refused ? { inputKey: refused.inputKey, origin: refused.origin } : null,
            }
        } catch (error) {
            logger.warn('🦔', '[HogExecutor] Secret origin check skipped due to an internal error', {
                error: error instanceof Error ? error.message : String(error),
                teamId: hogFunction.team_id,
                functionId: hogFunction.id,
            })
            return { mode, outcomes: ['error'], refusal: null }
        }
    }

    private warn(hogFunction: CheckedHogFunction, inputKey: string, origin: string, mode: SecretOriginCheckMode): void {
        const key = `${hogFunction.id}:${inputKey}:${origin}`
        if (this.warned.has(key)) {
            return
        }
        this.warned.set(key, true)
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
