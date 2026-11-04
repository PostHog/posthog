import { clearPending } from '@/core/approval'
import { defineCommand } from '@/core/command'
import { escapeControls } from '@/core/output'
import { PERSONAL_API_KEY_ENV_VAR } from '@/posthog/credentials'
import { LOGIN_COMMAND } from '@/posthog/login/flow'
import { logout, logoutAll, type LoggedOutHost } from '@/posthog/login/stored'
import { readSettings } from '@/posthog/settings'

interface LogoutResult {
    status: 'logged_out' | 'not_logged_in'
    host: string | null
    revokeUrl: string | null
    // Why hog couldn't remove the keychain item a file login left behind. Null when there was none.
    keychainLeftover: string | null
    // Every host `--all` logged out of. Null without `--all`.
    hosts: LoggedOutHost[] | null
    // Variables that still give hog a key after logout.
    stillSet: string[]
}

export default defineCommand({
    description: 'Remove the personal API key hog stored on this machine',
    writes: true,
    notes: 'The key itself stays valid until you delete it in PostHog under Settings > Personal API keys.',
    options: {
        all: { type: 'boolean', description: 'Log out of every PostHog host hog has a login for' },
    },
    examples: ['hog auth logout', 'hog auth logout --host https://eu.posthog.com', 'hog auth logout --all'],

    async run({ options, ctx }): Promise<LogoutResult> {
        const { runtime } = ctx
        const stillSet = runtime.env[PERSONAL_API_KEY_ENV_VAR] ? [PERSONAL_API_KEY_ENV_VAR] : []
        if (options.all) {
            const hosts = await logoutAll(runtime)
            await clearPending(runtime, LOGIN_COMMAND)
            const status = hosts.length > 0 ? 'logged_out' : 'not_logged_in'
            return { status, host: null, revokeUrl: null, keychainLeftover: null, hosts, stillSet }
        }
        const settings = await readSettings(runtime)
        // The same host order commands use, so logout removes the login they would send. A broken
        // posthog.json must not stop a logout.
        const configHost = (await ctx.config().catch(() => undefined))?.config.host
        const host = ctx.globals.host ?? configHost ?? settings.host
        const outcome = host ? await logout(runtime, host) : undefined
        await clearPending(runtime, LOGIN_COMMAND)
        return {
            status: outcome ? 'logged_out' : 'not_logged_in',
            host: host ?? null,
            revokeUrl: outcome?.revokeUrl ?? null,
            keychainLeftover: outcome?.keychainLeftover ?? null,
            hosts: null,
            stillSet,
        }
    },

    human({ result, out }) {
        const loggedOut = result.hosts ?? (result.host && result.status === 'logged_out' ? [result] : [])
        if (loggedOut.length === 0) {
            out.line('hog had no stored key to remove.')
        }
        for (const { host, revokeUrl, keychainLeftover } of loggedOut) {
            out.line(`${out.style('Logged out', 'green', 'bold')} of ${escapeControls(host ?? '')}.`)
            if (keychainLeftover) {
                out.line(
                    out.style(
                        `hog couldn't remove an older copy of the key from the keychain: ${keychainLeftover} Remove the hog item for ${escapeControls(host ?? '')} from the keychain yourself.`,
                        'yellow'
                    )
                )
            }
            if (revokeUrl) {
                out.line(out.style(`The key still works until you delete it at ${revokeUrl}`, 'dim'))
            }
        }
        if (result.stillSet.length > 0) {
            out.line(
                `${out.style('Still logged in', 'yellow', 'bold')} through ${result.stillSet.join(' and ')}. Unset it to log out fully.`
            )
        }
    },
})
