import { z } from 'zod'

import { parser } from '@/core/schema'
import { capitalize } from '@/core/text'

// The prefixes PostHog issues, from posthog/models/utils.py.
const TOKEN_KINDS = {
    personalApiKey: { prefix: 'phx_', name: 'a personal API key' },
    projectToken: { prefix: 'phc_', name: 'a project token' },
    // Project secret API keys and team secret tokens share the prefix.
    projectSecretApiKey: { prefix: 'phs_', name: 'a project secret API key' },
    teamSecretToken: { prefix: 'phs_', name: 'a team secret token' },
    oauthAccessToken: { prefix: 'pha_', name: 'an OAuth access token' },
    oauthRefreshToken: { prefix: 'phr_', name: 'an OAuth refresh token' },
} as const

type TokenKind = keyof typeof TOKEN_KINDS

// `phs_` names both secret kinds, because hog can't tell them apart.
const PREFIX_NAMES: Record<string, string> = {
    ...Object.fromEntries(Object.values(TOKEN_KINDS).map(({ prefix, name }) => [prefix, name])),
    phs_: 'a secret API key',
}

// New tokens are base57 and older ones URL-safe base64, so both fit.
const TOKEN_BODY = /^[A-Za-z0-9_-]+$/

const JWT = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/

// The problem never contains the value, which would end up in logs and agent transcripts.
function tokenProblem(value: string, name: string, rule: string): string {
    const other = PREFIX_NAMES[value.slice(0, 4)]
    return other
        ? `This is ${other}, not ${name}. ${capitalize(name)} must ${rule}.`
        : `This doesn't look like ${name}: it must ${rule}.`
}

// For a token that starts with its prefix: what is wrong with the rest of it.
function bodyProblem(value: string, prefix: string, noun: string): string | undefined {
    const body = value.slice(prefix.length)
    if (body === '') {
        return `The ${noun} is cut off: nothing follows ${prefix}.`
    }
    return TOKEN_BODY.test(body)
        ? undefined
        : `The ${noun} has characters a token can't have, such as a space or a quote. Copy it again.`
}

function tokenSchema(kind: TokenKind): z.ZodString {
    const { prefix, name } = TOKEN_KINDS[kind]
    const noun = name.replace(/^an? /, '')
    return z.string({ error: `The ${noun} must be text.` }).check((ctx) => {
        const value = ctx.value
        const problem = value.startsWith(prefix)
            ? bodyProblem(value, prefix, noun)
            : tokenProblem(value, name, `start with ${prefix}`)
        if (problem) {
            ctx.issues.push({ code: 'custom', input: value, message: problem })
        }
    })
}

// PostHog also accepts a custom project token without the prefix, so only an empty token or one
// with another kind's prefix fails.
function projectTokenProblem(value: string): string | undefined {
    const { prefix, name } = TOKEN_KINDS.projectToken
    if (value.startsWith(prefix)) {
        return bodyProblem(value, prefix, 'project token')
    }
    const other = PREFIX_NAMES[value.slice(0, 4)]
    if (other) {
        return `This is ${other}, not ${name}.`
    }
    return value === '' ? 'The project token is empty.' : undefined
}

export const PersonalApiKeySchema = tokenSchema('personalApiKey').brand<'PersonalApiKey'>()
export const ProjectTokenSchema = z
    .string({ error: 'The project token must be text.' })
    .check((ctx) => {
        const problem = projectTokenProblem(ctx.value)
        if (problem) {
            ctx.issues.push({ code: 'custom', input: ctx.value, message: problem })
        }
    })
    .brand<'ProjectToken'>()
export const ProjectSecretApiKeySchema = tokenSchema('projectSecretApiKey').brand<'ProjectSecretApiKey'>()
export const TeamSecretTokenSchema = tokenSchema('teamSecretToken').brand<'TeamSecretToken'>()
export const OAuthAccessTokenSchema = tokenSchema('oauthAccessToken').brand<'OAuthAccessToken'>()
export const OAuthRefreshTokenSchema = tokenSchema('oauthRefreshToken').brand<'OAuthRefreshToken'>()

// A workload token is a JWT, which has no PostHog prefix.
export const WorkloadTokenSchema = z
    .string({ error: 'The workload token must be text.' })
    .check((ctx) => {
        if (!JWT.test(ctx.value)) {
            const message = tokenProblem(ctx.value, 'a workload token', 'be a JWT, three parts joined by dots')
            ctx.issues.push({ code: 'custom', input: ctx.value, message })
        }
    })
    .brand<'WorkloadToken'>()

export type PersonalApiKey = z.output<typeof PersonalApiKeySchema>
export type ProjectToken = z.output<typeof ProjectTokenSchema>
export type ProjectSecretApiKey = z.output<typeof ProjectSecretApiKeySchema>
export type TeamSecretToken = z.output<typeof TeamSecretTokenSchema>
export type OAuthAccessToken = z.output<typeof OAuthAccessTokenSchema>
export type OAuthRefreshToken = z.output<typeof OAuthRefreshTokenSchema>
export type WorkloadToken = z.output<typeof WorkloadTokenSchema>

export type BearerToken = PersonalApiKey | OAuthAccessToken

const LOG_IN_AGAIN = 'Run `hog auth login` to log in again.'
const PROJECT_SETTINGS = 'Copy it again from Settings > Project in PostHog.'

export const parsePersonalApiKey = parser(PersonalApiKeySchema, {
    code: 'invalid_personal_api_key',
    hint: 'Create a personal API key in PostHog under Settings > Personal API keys.',
})
export const parseProjectToken = parser(ProjectTokenSchema, { code: 'invalid_project_token', hint: PROJECT_SETTINGS })
export const parseProjectSecretApiKey = parser(ProjectSecretApiKeySchema, {
    code: 'invalid_project_secret_api_key',
    hint: PROJECT_SETTINGS,
})
export const parseTeamSecretToken = parser(TeamSecretTokenSchema, {
    code: 'invalid_team_secret_token',
    hint: PROJECT_SETTINGS,
})
export const parseOAuthAccessToken = parser(OAuthAccessTokenSchema, {
    code: 'invalid_oauth_access_token',
    hint: LOG_IN_AGAIN,
})
export const parseOAuthRefreshToken = parser(OAuthRefreshTokenSchema, {
    code: 'invalid_oauth_refresh_token',
    hint: LOG_IN_AGAIN,
})
export const parseWorkloadToken = parser(WorkloadTokenSchema, { code: 'invalid_workload_token' })
