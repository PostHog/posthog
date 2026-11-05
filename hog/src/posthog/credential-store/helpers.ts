import { z } from 'zod'

import { parseOrUndefined } from '@/core/schema'
import { OAuthAccessTokenSchema, OAuthRefreshTokenSchema, PersonalApiKeySchema } from '@/posthog/tokens'

import type { StoredSecret } from './types'

export function parseJson(text: string): unknown {
    try {
        return JSON.parse(text)
    } catch {
        return undefined
    }
}

const StoredSecretSchema = z.union([
    z.object({ apiKey: PersonalApiKeySchema }),
    z.object({ accessToken: OAuthAccessTokenSchema, refreshToken: OAuthRefreshTokenSchema }),
])

// A stored value hog doesn't recognize, such as one a later version wrote, reads as no login.
export function parseSecret(value: unknown): StoredSecret | undefined {
    return parseOrUndefined(StoredSecretSchema, value)
}
