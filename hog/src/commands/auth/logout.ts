import { clearPending } from '@/core/approval'
import { defineCommand } from '@/core/command'
import { escapeControls } from '@/core/output'
import { PERSONAL_API_KEY_ENV_VAR, posthogCliCredentialsPath } from '@/posthog/credentials'
import { LOGIN_COMMAND } from '@/posthog/login'
import { readLogin, removeLogin } from '@/posthog/logins'
import { readSettings } from '@/posthog/settings'

interface LogoutResult {
    status: 'logged_out' | 'not_logged_in'
    host: string | null
    revokeUrl: string | null
    // Variables that still give hog a key after logout.
    stillSet: string[]
    // posthog-cli's credentials file, which hog still reads and never changes.
    posthogCliFile: string | null
}

export default defineCommand({
    description: 'Remove the personal API key hog stored on this machine',
    writes: true,
    notes: [
        'The key itself stays valid until you delete it in PostHog under Settings > Personal API keys.',
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
        const removed = login ? await removeLogin(runtime, login) : false
        await clearPending(runtime, LOGIN_COMMAND)
        const posthogCliFile = posthogCliCredentialsPath(runtime)
        return {
            status: removed ? 'logged_out' : 'not_logged_in',
            host: host ?? null,
            revokeUrl:
                removed && host ? new URL('settings/user-api-keys', `${host.replace(/\/+$/, '')}/`).toString() : null,
            stillSet: runtime.env[PERSONAL_API_KEY_ENV_VAR] ? [PERSONAL_API_KEY_ENV_VAR] : [],
            posthogCliFile: (await runtime.exists(posthogCliFile)) ? posthogCliFile : null,
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
        if (result.posthogCliFile) {
            out.line(
                `${out.style('Still logged in', 'yellow', 'bold')} through posthog-cli's credentials file, ${result.posthogCliFile}. hog never changes that file.`
            )
        }
    },
})
