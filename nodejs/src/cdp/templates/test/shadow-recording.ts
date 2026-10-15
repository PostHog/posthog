import { parseJSON } from '~/common/utils/json-parse'

import type { OutgoingRequest } from './template-pipeline'

export type RecordedRequest = {
    method: string
    url: string
    headers: Record<string, string>
    body?: unknown
}

export type NormalizeContext = {
    sensitiveValues: string[]
    /** Every value the run started from. A UUID found here is data, any other UUID was generated during the run. */
    inputText: string
    /** Each run creates its own team, so its id differs between two otherwise identical runs. */
    teamId: number
}

const SECRET_MARKER = '<secret>'
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi
const BASIC_AUTH = /^Basic (.+)$/
const JWT = /eyJ[\w-]+\.([\w-]+)\.[\w-]+/g

export const normalizeRequests = (requests: OutgoingRequest[], context: NormalizeContext): RecordedRequest[] => {
    const normalizeText = textNormalizer(context)

    return requests.map((request) => ({
        method: request.method.toUpperCase(),
        url: normalizeText(request.url),
        headers: sortKeys(
            Object.fromEntries(
                Object.entries(request.headers).map(([name, value]) => [name, normalizeText(decodeBasicAuth(value))])
            )
        ) as Record<string, string>,
        ...(request.body === undefined ? {} : { body: sortKeys(parseBody(normalizeText(request.body))) }),
    }))
}

export const normalizeValue = (value: unknown, context: NormalizeContext): unknown =>
    sortKeys(parseJSON(textNormalizer(context)(JSON.stringify(value))))

const textNormalizer = (context: NormalizeContext): ((text: string) => string) => {
    const generatedUuids = new Map<string, string>()
    const teamIdInPath = new RegExp(`(?<=/projects?/)${context.teamId}(?=[/?#"]|$)`, 'g')
    return (text) =>
        maskGeneratedUuids(
            maskSecrets(replaceSignedTokens(text, context.teamId), context.sensitiveValues),
            context.inputText,
            generatedUuids
        ).replace(teamIdInPath, '<team_id>')
}

const replaceSignedTokens = (text: string, teamId: number): string =>
    text.replace(JWT, (_token, payload: string) => {
        const claims = parseJSON(Buffer.from(payload, 'base64url').toString('utf-8')) as Record<string, unknown>
        const rendered = Object.keys(claims)
            .sort()
            .map((key) => `${key}=${claimValue(key, claims[key], teamId)}`)
        return `<jwt ${rendered.join(' ')}>`
    })

const claimValue = (key: string, value: unknown, teamId: number): string => {
    if (key === 'team_id' && value === teamId) {
        return '<team_id>'
    }
    return typeof value === 'string' ? value : JSON.stringify(value)
}

const maskSecrets = (text: string, sensitiveValues: string[]): string =>
    sensitiveValues
        .filter((value) => value.length > 0)
        .reduce((masked, value) => masked.replaceAll(value, SECRET_MARKER), text)

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
