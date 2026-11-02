import { defineCommand } from '@/core/command'
import { escapeControls } from '@/core/output'
import { PERSONAL_API_KEY_ENV_VAR } from '@/posthog/credentials'
import { clearPendingLogin } from '@/posthog/login'
import { readLogin, removeLogin } from '@/posthog/logins'
import { readSettings } from '@/posthog/settings'

interface LogoutResult {
    status: 'logged_out' | 'not_logged_in'
    host: string | null
    revokeUrl: string | null
    // Variables that still give hog a key after logout.
    stillSet: string[]
}

export default defineCommand({
    description: 'Remove the personal API key hog stored on this machine',
    writes: true,
    notes: ['The key itself stays valid until you delete it in PostHog under Settings > Personal API keys.'].join('\n'),
    examples: ['hog auth logout', 'hog auth logout --host https://eu.posthog.com'],

    async run({ ctx }): Promise<LogoutResult> {
        const { runtime } = ctx
        const settings = await readSettings(runtime)
        // The same host order commands use, so logout removes the login they would send. A broken
        // posthog.json must not stop a logout.
        const configHost = (await ctx.config().catch(() => undefined))?.config.host
        const host = ctx.globals.host ?? configHost ?? settings.host
        const login = host ? await readLogin(runtime, settings, host) : undefined
        const [outcome, removed] = await Promise.all([
            login?.credential.logout(runtime),
            login ? removeLogin(runtime, login) : false,
        ])
        await clearPendingLogin(runtime)
        return {
            status: removed ? 'logged_out' : 'not_logged_in',
            host: host ?? null,
            revokeUrl: removed ? (outcome?.revokeUrl ?? null) : null,
            stillSet: runtime.env[PERSONAL_API_KEY_ENV_VAR] ? [PERSONAL_API_KEY_ENV_VAR] : [],
        }
    },

    human({ result, out }) {
        out.line(
            result.status === 'logged_out'
                ? `${out.style('Logged out', 'green', 'bold')} of ${escapeControls(result.host ?? '')}.`
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
