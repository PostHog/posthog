import jwt from 'jsonwebtoken'

export enum PosthogJwtAudience {
    RECORDING_API = 'posthog:recording_api',
    SUBSCRIPTION_PREFERENCES = 'posthog:messaging:subscription_preferences',
    WORKFLOWS_RESCHEDULE_PARKED = 'posthog:workflows:reschedule_parked',
    WORKFLOWS_CANCEL_INVOCATIONS = 'posthog:workflows:cancel_invocations',
    WORKFLOWS_CANCEL_BATCH = 'posthog:workflows:cancel_batch',
    TASKS_CREATE = 'posthog:tasks:create',
    // Must match PosthogJwtAudience.CONVERSATIONS_TICKETS in posthog/jwt.py exactly.
    CONVERSATIONS_TICKETS = 'posthog:conversations:tickets',
}

export class JWT {
    private secrets: string[] = []

    constructor(commaSeparatedSaltKeys: string) {
        const saltKeys = parseJwtKeys(commaSeparatedSaltKeys)
        if (!saltKeys.length) {
            throw new Error('Encryption keys are not set')
        }
        this.secrets = saltKeys
    }

    sign(payload: object, audience: PosthogJwtAudience, options?: jwt.SignOptions): string {
        return jwt.sign(payload, this.secrets[0], { ...options, audience: audience })
    }

    verify(
        token: string,
        audience: PosthogJwtAudience,
        options?: jwt.VerifyOptions & { ignoreVerificationErrors?: boolean }
    ): string | jwt.Jwt | jwt.JwtPayload | undefined {
        let error: Error | undefined
        for (const secret of this.secrets) {
            try {
                const payload = jwt.verify(token, secret, { ...options, audience: audience })
                return payload
            } catch (e) {
                error = e
            }
        }
        if (options?.ignoreVerificationErrors) {
            return undefined
        }
        throw error
    }
}

/** Split a comma-separated key string into usable keys (newest first), trimming each and dropping
 * empty segments. Trimming keeps this in lockstep with the Python minter's recording_api_signing_keys. */
export function parseJwtKeys(commaSeparatedSaltKeys: string): string[] {
    return commaSeparatedSaltKeys
        .split(',')
        .map((key) => key.trim())
        .filter((key) => key)
}

/** Whether a comma-separated key string yields at least one usable key. */
export function hasJwtKeys(commaSeparatedSaltKeys: string): boolean {
    return parseJwtKeys(commaSeparatedSaltKeys).length > 0
}

/** Build a verifier, or null when no usable key is configured, so a malformed-but-truthy value like
 * ',' disables JWT instead of throwing at construction. */
export function makeOptionalJwt(commaSeparatedSaltKeys: string): JWT | null {
    return hasJwtKeys(commaSeparatedSaltKeys) ? new JWT(commaSeparatedSaltKeys) : null
}
