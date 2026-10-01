import type { UserCodexAuthTokensApi } from '~/generated/core/api.schemas'

export type CodexAuthFileResult = { tokens: UserCodexAuthTokensApi; error: null } | { tokens: null; error: string }

function readString(value: unknown): string | null {
    return typeof value === 'string' && value.trim() ? value.trim() : null
}

export function parseCodexAuthFile(text: string): CodexAuthFileResult {
    let parsed: unknown
    try {
        parsed = JSON.parse(text)
    } catch {
        return { tokens: null, error: 'This is not valid JSON. Copy the full contents of the auth.json file.' }
    }
    const rawTokens = parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>).tokens : undefined
    if (!rawTokens || typeof rawTokens !== 'object') {
        return {
            tokens: null,
            error: 'This file has no ChatGPT sign-in. Run the login command again and sign in with ChatGPT, not with an API key.',
        }
    }
    const tokens = rawTokens as Record<string, unknown>
    const accessToken = readString(tokens.access_token)
    const refreshToken = readString(tokens.refresh_token)
    if (!accessToken || !refreshToken) {
        return { tokens: null, error: 'This file is missing its tokens. Run the login command again.' }
    }
    return {
        tokens: { access_token: accessToken, refresh_token: refreshToken, id_token: readString(tokens.id_token) },
        error: null,
    }
}
