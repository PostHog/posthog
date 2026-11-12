import { z } from 'zod'

import { OAuthAccessTokenSchema, OAuthRefreshTokenSchema, PersonalApiKeySchema } from '@/posthog/tokens'

export const StoredSecretSchema = z.union([
    z.object({ apiKey: PersonalApiKeySchema }),
    z.object({ accessToken: OAuthAccessTokenSchema, refreshToken: OAuthRefreshTokenSchema }),
])
