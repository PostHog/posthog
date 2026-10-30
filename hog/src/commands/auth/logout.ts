import { defineCommand } from '@/core/command'
import { API_KEY_ENV_VAR, posthogFile } from '@/posthog/credentials'
import { clearPendingLogin } from '@/posthog/login'

interface LogoutResult {
    status: 'logged_out' | 'not_logged_in'
    credentialsPath: string
    revokeUrl: string | null
    // Variables that still give hog a key after logout.
    stillSet: string[]
}

export default defineCommand({
    description: 'Remove the personal API key hog stored on this machine',
    writes: true,
    notes: 'The key itself stays valid until you delete it in PostHog under Settings > Personal API keys.',
    examples: ['hog auth logout'],

    async run({ ctx }): Promise<LogoutResult> {
        const { runtime } = ctx
        const credentialsPath = posthogFile(runtime, 'credentials.json')
        let host: string | undefined
        let stored = false
        try {
            host = (JSON.parse(await runtime.readFile(credentialsPath)) as { host?: string }).host
            stored = true
        } catch {
            stored = false
        }
        await runtime.removeFile(credentialsPath)
        await clearPendingLogin(runtime)
        return {
            status: stored ? 'logged_out' : 'not_logged_in',
            credentialsPath,
            revokeUrl: host ? new URL('settings/user-api-keys', `${host.replace(/\/+$/, '')}/`).toString() : null,
            stillSet: runtime.env[API_KEY_ENV_VAR] ? [API_KEY_ENV_VAR] : [],
        }
    },

    human({ result, out }) {
        out.line(
            result.status === 'logged_out'
                ? `${out.style('Logged out', 'green', 'bold')}. Removed ${result.credentialsPath}.`
                : 'hog had no stored key to remove.'
        )
        if (result.revokeUrl) {
            out.line(out.style(`The key still works until you delete it at ${result.revokeUrl}`, 'dim'))
        }
        if (result.stillSet.length > 0) {
            out.line(
                `${out.style('Still logged in', 'yellow', 'bold')} through ${result.stillSet.join(' and ')}. Unset it to log out fully.`
            )
        }
    },
})
