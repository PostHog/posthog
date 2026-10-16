import { parseJSON } from '~/common/utils/json-parse'

import type { OutgoingRequest } from './template-pipeline'

export type RecordedRequest = {
    method: string
    url: string
    headers: Record<string, string>
    body?: unknown
}

export type NormalizeContext = {
    /** Each secret is recorded as `<secret:name>`, so a request that sends one secret in place of another differs. */
    secrets: Record<string, string>
    /** Every value the run started from. A UUID found here is data, any other UUID was generated during the run. */
    inputText: string
    /** Each run creates its own team, so its id differs between two otherwise identical runs. */
    teamId: number
}

type TextNormalizer = (text: string) => string

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi
const BASIC_AUTH = /^Basic (.+)$/
const SIGNATURE_HEADER = /signature/i
const JWT = /eyJ[\w-]+\.([\w-]+)\.[\w-]+/g
const BASE64_RUN = /[A-Za-z0-9+/_-]{16,}={0,2}/g

export const normalizeRequests = (requests: OutgoingRequest[], context: NormalizeContext): RecordedRequest[] => {
    const normalizeText = textNormalizer(context)

    return requests.map((request) => ({
        method: request.method.toUpperCase(),
        url: normalizeText(request.url),
        headers: sortKeys(
            Object.fromEntries(
                Object.entries(request.headers).map(([name, value]) => [
                    name,
                    normalizeHeader(name, value, normalizeText),
                ])
            )
        ) as Record<string, string>,
        ...(request.body === undefined ? {} : { body: normalizeLeaves(parseBody(request.body), normalizeText) }),
    }))
}

// A signature covers the generated delivery id, so it differs on every run. Its inputs are recorded beside it.
const normalizeHeader = (name: string, value: string, normalizeText: TextNormalizer): string =>
    SIGNATURE_HEADER.test(name) ? '<signature>' : normalizeText(decodeBasicAuth(value))

export const normalizeValue = (value: unknown, context: NormalizeContext): unknown =>
    normalizeLeaves(value, textNormalizer(context))

const normalizeLeaves = (value: unknown, normalizeText: TextNormalizer): unknown => {
    const sorted = sortKeys(value)
    if (typeof sorted === 'string') {
        return normalizeText(sorted)
    }
    if (Array.isArray(sorted)) {
        return sorted.map((item) => normalizeLeaves(item, normalizeText))
    }
    if (sorted && typeof sorted === 'object') {
        return Object.fromEntries(
            Object.entries(sorted).map(([key, item]) => [key, normalizeLeaves(item, normalizeText)])
        )
    }
    return sorted
}

const textNormalizer = (context: NormalizeContext): TextNormalizer => {
    const generatedUuids = new Map<string, string>()
    const teamIdInPath = new RegExp(`(?<=/projects?/)${context.teamId}(?=[/?#"]|$)`, 'g')
    const secrets = secretVariants(context.secrets)
    return (text) => {
        const decoded = decodeBase64RunsWithSecrets(replaceSignedTokens(text, context.teamId), secrets)
        const masked = secrets.reduce((result, [variant, marker]) => result.replaceAll(variant, marker), decoded)
        return maskGeneratedUuids(masked, context.inputText, generatedUuids).replace(teamIdInPath, '<team_id>')
    }
}

/** Every form a template can send a secret in, longest first so a longer form is masked before a shorter one inside it. */
const secretVariants = (secrets: Record<string, string>): [string, string][] =>
    Object.entries(secrets)
        .filter(([, value]) => value.length > 0)
        .flatMap(([name, value]): [string, string][] =>
            [
                value,
                encodeURIComponent(value),
                JSON.stringify(value).slice(1, -1),
                Buffer.from(value).toString('base64'),
                Buffer.from(value).toString('base64url'),
            ].map((variant) => [variant, `<secret:${name}>`])
        )
        .sort(([a], [b]) => b.length - a.length)

const decodeBase64RunsWithSecrets = (text: string, secrets: [string, string][]): string =>
    text.replace(BASE64_RUN, (run) => {
        const decoded = Buffer.from(run, run.includes('-') || run.includes('_') ? 'base64url' : 'base64').toString(
            'utf-8'
        )
        return secrets.some(([variant]) => decoded.includes(variant)) ? `<base64>${decoded}</base64>` : run
    })

const replaceSignedTokens = (text: string, teamId: number): string =>
    text.replace(JWT, (token, payload: string) => {
        const claims = parseClaims(payload)
        if (!claims) {
            return token
        }
        const rendered = Object.keys(claims)
            .sort()
            .map((key) => `${key}=${claimValue(key, claims[key], teamId)}`)
        return `<jwt ${rendered.join(' ')}>`
    })

const parseClaims = (payload: string): Record<string, unknown> | null => {
    try {
        const claims: unknown = parseJSON(Buffer.from(payload, 'base64url').toString('utf-8'))
        return claims && typeof claims === 'object' && !Array.isArray(claims)
            ? (claims as Record<string, unknown>)
            : null
    } catch {
        return null
    }
}

const claimValue = (key: string, value: unknown, teamId: number): string => {
    if (key === 'team_id' && value === teamId) {
        return '<team_id>'
    }
    return typeof value === 'string' ? value : JSON.stringify(sortKeys(value))
}

const maskGeneratedUuids = (text: string, inputText: string, generatedUuids: Map<string, string>): string =>
    text.replace(UUID, (uuid) => {
        if (inputText.includes(uuid)) {
            return uuid
        }
        if (!generatedUuids.has(uuid)) {
            generatedUuids.set(uuid, `<uuid-${generatedUuids.size + 1}>`)
        }
        return generatedUuids.get(uuid)!
    })

const decodeBasicAuth = (value: string): string => {
    const match = BASIC_AUTH.exec(value)
    return match ? `Basic <decoded>${Buffer.from(match[1], 'base64').toString('utf-8')}` : value
}

const parseBody = (body: string): unknown => {
    try {
        return parseJSON(body)
    } catch {
        return body
    }
}

const sortKeys = (value: unknown): unknown => {
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value && typeof value === 'object') {
        return Object.fromEntries(
            Object.keys(value)
                .sort()
                .map((key) => [key, sortKeys((value as Record<string, unknown>)[key])])
        )
    }
    return value
}
