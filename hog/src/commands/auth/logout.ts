import { clearPending } from '@/core/approval'
import { defineCommand } from '@/core/command'
import { PERSONAL_API_KEY_ENV_VAR, posthogCliCredentialsPath } from '@/posthog/credentials'
import { revokeLogin } from '@/posthog/device-auth'
import { LOGIN_COMMAND } from '@/posthog/login'
import { readLogin, removeLogin } from '@/posthog/logins'
import { readSettings } from '@/posthog/settings'

interface LogoutResult {
    status: 'logged_out' | 'not_logged_in'
    host: string | null
    // Whether PostHog revoked the OAuth login. Null for a personal API key, which hog can't revoke.
    revoked: boolean | null
    // Where to delete a personal API key, which keeps working after logout.
    revokeUrl: string | null
    // Variables that still give hog a key after logout.
    stillSet: string[]
    // posthog-cli's credentials file, which hog still reads and never changes.
    posthogCliFile: string | null
}

export default defineCommand({
    description: 'Log out of PostHog and remove the login hog stored on this machine',
    writes: true,
    notes: [
        'hog revokes the login on this machine in PostHog. Your hog logins on other machines keep working.',
        'A personal API key you pasted stays valid until you delete it in PostHog under Settings > Personal API keys.',
        "hog never changes posthog-cli's credentials file, so it still reads a key from there after logout.",
    ].join('\n'),
    examples: ['hog auth logout', 'hog auth logout --host https://eu.posthog.com'],

    async run({ ctx }): Promise<LogoutResult> {
        const { runtime } = ctx
        const settings = await readSettings(runtime)
        // The same host order commands use, so logout removes the login they would send. A broken
        // posthog.json must not stop a logout.
        const configHost = (await ctx.config().catch(() => undefined))?.config.host
        const host = ctx.globals.host ?? configHost ?? settings.host
        const login = host ? await readLogin(runtime, settings, host) : undefined
        const stored = login?.credential
        const personalApiKey = stored?.type === 'personal_api_key'
        const [revoked, removed] = await Promise.all([
            stored?.type === 'oauth' ? revokeLogin(runtime, stored) : null,
            login ? removeLogin(runtime, login) : false,
        ])
        await clearPending(runtime, LOGIN_COMMAND)
        const posthogCliFile = posthogCliCredentialsPath(runtime)
        return {
            status: removed ? 'logged_out' : 'not_logged_in',
            host: host ?? null,
            revoked,
            revokeUrl:
                personalApiKey && host
                    ? new URL('settings/user-api-keys', `${host.replace(/\/+$/, '')}/`).toString()
                    : null,
            stillSet: runtime.env[PERSONAL_API_KEY_ENV_VAR] ? [PERSONAL_API_KEY_ENV_VAR] : [],
            posthogCliFile: (await runtime.exists(posthogCliFile)) ? posthogCliFile : null,
        }
    },

    human({ result, out }) {
        out.line(
            result.status === 'logged_out'
                ? `${out.style('Logged out', 'green', 'bold')} of ${result.host}.`
                : 'hog had no stored login to remove.'
        )
        if (result.revoked === false) {
            out.line(
                out.style(
                    "hog couldn't reach PostHog to revoke the login, so it keeps working in PostHog. Revoke it under Settings > Connected applications.",
                    'yellow'
                )
            )
        }
        if (result.revokeUrl) {
            out.line(out.style(`The key still works until you delete it at ${result.revokeUrl}`, 'dim'))
        }
        if (result.stillSet.length > 0) {
            out.line(
                `${out.style('Still logged in', 'yellow', 'bold')} through ${result.stillSet.join(' and ')}. Unset it to log out fully.`
            )
        }
        if (result.posthogCliFile) {
            out.line(
                `${out.style('Still logged in', 'yellow', 'bold')} through posthog-cli's credentials file, ${result.posthogCliFile}. hog never changes that file.`
            )
        }
    },
})
