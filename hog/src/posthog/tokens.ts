import { z } from 'zod'

import { parseOrThrow, type ParseFailure } from '@/core/schema'

// What each prefix PostHog issues means, from posthog/models/utils.py. Project secret API keys and
// team secret tokens share `phs_`, so hog can't tell them apart.
const KNOWN_PREFIXES: Record<string, string> = {
    phx_: 'a personal API key',
    phc_: 'a project token',
    phs_: 'a secret API key',
    pha_: 'an OAuth access token',
    phr_: 'an OAuth refresh token',
}

// The message never contains the value, which would end up in logs and agent transcripts.
function tokenError(value: unknown, name: string, rule: string): string {
    const other = typeof value === 'string' ? KNOWN_PREFIXES[value.slice(0, 4)] : undefined
    return other
        ? `This is ${other}, not ${name}, which must ${rule}.`
        : `This doesn't look like ${name}: it must ${rule}.`
}

// New tokens are base57 and older ones URL-safe base64, so the part after the prefix fits both.
function prefixedToken(prefix: string, name: string): z.ZodString {
    return z.string({ error: 'The token must be text.' }).regex(new RegExp(`^${prefix}[A-Za-z0-9_-]+$`), {
        error: (issue) =>
            typeof issue.input === 'string' && issue.input.startsWith(prefix)
                ? `This token is cut off, or has characters a token can't have, such as a space or a quote. Copy it again.`
                : tokenError(issue.input, name, `start with ${prefix}`),
    })
}

// PostHog also accepts a custom project token, with or without the prefix and with any characters,
// so only an empty token or one with another kind's prefix fails.
function projectTokenError(value: string): string | undefined {
    if (value === '' || value === 'phc_') {
        return 'The project token is empty.'
    }
    const other = value.startsWith('phc_') ? undefined : KNOWN_PREFIXES[value.slice(0, 4)]
    return other ? `This is ${other}, not a project token.` : undefined
}

export const PersonalApiKeySchema = prefixedToken('phx_', 'a personal API key').brand<'PersonalApiKey'>()
export const ProjectSecretApiKeySchema = prefixedToken(
    'phs_',
    'a project secret API key'
).brand<'ProjectSecretApiKey'>()
export const TeamSecretTokenSchema = prefixedToken('phs_', 'a team secret token').brand<'TeamSecretToken'>()
export const OAuthAccessTokenSchema = prefixedToken('pha_', 'an OAuth access token').brand<'OAuthAccessToken'>()
export const OAuthRefreshTokenSchema = prefixedToken('phr_', 'an OAuth refresh token').brand<'OAuthRefreshToken'>()

export const ProjectTokenSchema = z
    .string({ error: 'The token must be text.' })
    .refine((value) => projectTokenError(value) === undefined, {
        error: (issue) => projectTokenError(String(issue.input)),
    })
    .brand<'ProjectToken'>()

function jwt(name: string): z.ZodString {
    return z.string({ error: 'The token must be text.' }).regex(/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/, {
        error: (issue) => tokenError(issue.input, name, 'be a JWT, three parts joined by dots'),
    })
}

// A workload token is a JWT, which has no PostHog prefix.
export const WorkloadTokenSchema = jwt('a workload token').brand<'WorkloadToken'>()
export const ProviderIdTokenSchema = jwt('an OIDC token').brand<'ProviderIdToken'>()

export type PersonalApiKey = z.output<typeof PersonalApiKeySchema>
export type ProjectToken = z.output<typeof ProjectTokenSchema>
export type ProjectSecretApiKey = z.output<typeof ProjectSecretApiKeySchema>
export type TeamSecretToken = z.output<typeof TeamSecretTokenSchema>
export type OAuthAccessToken = z.output<typeof OAuthAccessTokenSchema>
export type OAuthRefreshToken = z.output<typeof OAuthRefreshTokenSchema>
export type WorkloadToken = z.output<typeof WorkloadTokenSchema>
export type ProviderIdToken = z.output<typeof ProviderIdTokenSchema>

export type BearerToken = PersonalApiKey | OAuthAccessToken | WorkloadToken

const LOG_IN_AGAIN = 'Run `hog auth login` to log in again.'
const PROJECT_SETTINGS = 'Copy it again from your project settings: https://app.posthog.com/settings/project-details'

export function parsePersonalApiKey(raw: unknown, failure?: Partial<ParseFailure>): PersonalApiKey {
    return parseOrThrow(PersonalApiKeySchema, raw, {
        code: 'invalid_personal_api_key',
        hint: 'Create a personal API key in PostHog: https://app.posthog.com/settings/user-api-keys',
        ...failure,
    })
}

export function parseProjectToken(raw: unknown, failure?: Partial<ParseFailure>): ProjectToken {
    return parseOrThrow(ProjectTokenSchema, raw, { code: 'invalid_project_token', hint: PROJECT_SETTINGS, ...failure })
}

export function parseProjectSecretApiKey(raw: unknown, failure?: Partial<ParseFailure>): ProjectSecretApiKey {
    return parseOrThrow(ProjectSecretApiKeySchema, raw, {
        code: 'invalid_project_secret_api_key',
        hint: PROJECT_SETTINGS,
        ...failure,
    })
}

export function parseTeamSecretToken(raw: unknown, failure?: Partial<ParseFailure>): TeamSecretToken {
    return parseOrThrow(TeamSecretTokenSchema, raw, {
        code: 'invalid_team_secret_token',
        hint: PROJECT_SETTINGS,
        ...failure,
    })
}

export function parseOAuthAccessToken(raw: unknown, failure?: Partial<ParseFailure>): OAuthAccessToken {
    return parseOrThrow(OAuthAccessTokenSchema, raw, {
        code: 'invalid_oauth_access_token',
        hint: LOG_IN_AGAIN,
        ...failure,
    })
}

export function parseOAuthRefreshToken(raw: unknown, failure?: Partial<ParseFailure>): OAuthRefreshToken {
    return parseOrThrow(OAuthRefreshTokenSchema, raw, {
        code: 'invalid_oauth_refresh_token',
        hint: LOG_IN_AGAIN,
        ...failure,
    })
}

export function parseWorkloadToken(raw: unknown, failure?: Partial<ParseFailure>): WorkloadToken {
    return parseOrThrow(WorkloadTokenSchema, raw, { code: 'invalid_workload_token', ...failure })
}

export function parseProviderIdToken(raw: unknown, failure?: Partial<ParseFailure>): ProviderIdToken {
    return parseOrThrow(ProviderIdTokenSchema, raw, { code: 'invalid_oidc_token', ...failure })
}
