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
        return {
            tokens: null,
            error: 'The clipboard does not hold a Codex sign-in. Run the command again, then paste.',
        }
    }
    const rawTokens = parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>).tokens : undefined
    if (!rawTokens || typeof rawTokens !== 'object') {
        return {
            tokens: null,
            error: 'This is not a ChatGPT sign-in. Run the command again and sign in with ChatGPT, not with an API key.',
        }
    }
    const tokens = rawTokens as Record<string, unknown>
    const accessToken = readString(tokens.access_token)
    const refreshToken = readString(tokens.refresh_token)
    if (!accessToken || !refreshToken) {
        return { tokens: null, error: 'This sign-in is missing its tokens. Run the command again.' }
    }
    return {
        tokens: { access_token: accessToken, refresh_token: refreshToken, id_token: readString(tokens.id_token) },
        error: null,
    }
}
