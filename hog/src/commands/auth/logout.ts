import { defineCommand } from '@/core/command'
import { escapeControls } from '@/core/output'
import { PERSONAL_API_KEY_ENV_VAR } from '@/posthog/credentials'
import { chooseLogin } from '@/posthog/login/choose'
import { clearPendingLogins } from '@/posthog/login/flow'
import { logout, logoutAll, type LoggedOutLogin } from '@/posthog/login/stored'
import { readSettings } from '@/posthog/settings'

interface LogoutResult {
    status: 'logged_out' | 'not_logged_in'
    // The login hog removed, or the one it looked for. Null with `--all`, or when hog has no login.
    host: string | null
    projectId: string | null
    // Whether PostHog revoked the OAuth login. Null for a personal API key, which hog can't revoke.
    revoked: boolean | null
    // Where to delete a personal API key, which keeps working after logout.
    revokeUrl: string | null
    // Why hog couldn't remove the keychain item a file login left behind. Null when there was none.
    keychainLeftover: string | null
    // Every login `--all` removed. Null without `--all`.
    logins: LoggedOutLogin[] | null
    // Variables that still give hog a key after logout.
    stillSet: string[]
}

export default defineCommand({
    description: 'Log out of PostHog and remove the login hog stored on this machine',
    writes: true,
    notes: [
        'hog removes the login commands in this folder use, the same one `hog auth status` shows. Logins to other projects stay.',
        'hog revokes the login on this machine in PostHog. Your hog logins on other machines keep working.',
        'A personal API key you pasted stays valid until you delete it in PostHog under Settings > Personal API keys.',
    ].join('\n'),
    options: {
        all: { type: 'boolean', description: 'Log out of every PostHog host and project hog has a login for' },
    },
    examples: ['hog auth logout', 'hog auth logout --host https://eu.posthog.com', 'hog auth logout --all'],

    async run({ options, ctx }): Promise<LogoutResult> {
        const { runtime } = ctx
        const stillSet = runtime.env[PERSONAL_API_KEY_ENV_VAR] ? [PERSONAL_API_KEY_ENV_VAR] : []

        if (options.all) {
            const logins = await logoutAll(runtime)
            await clearPendingLogins(runtime)
            const status = logins.length > 0 ? 'logged_out' : 'not_logged_in'

            return {
                status,
                host: null,
                projectId: null,
                revoked: null,
                revokeUrl: null,
                keychainLeftover: null,
                logins,
                stillSet,
            }
        }

        const settings = await readSettings(runtime)
        // The same choice commands make, so logout removes the login they would send.
        const { choice, record } = chooseLogin(settings, await ctx.loginQuery())
        const outcome = record ? await logout(runtime, record) : undefined
        await clearPendingLogins(runtime)

        return {
            status: outcome ? 'logged_out' : 'not_logged_in',
            host: record?.host ?? choice.host,
            projectId: record?.projectId ?? choice.projectId,
            revoked: outcome?.revoked ?? null,
            revokeUrl: outcome?.revokeUrl ?? null,
            keychainLeftover: outcome?.keychainLeftover ?? null,
            logins: null,
            stillSet,
        }
    },

    human({ result, out }) {
        const loggedOut = result.logins ?? (result.host && result.status === 'logged_out' ? [result] : [])
        if (loggedOut.length === 0) {
            const which =
                result.host && result.projectId
                    ? ` for project ${result.projectId} on ${escapeControls(result.host)}`
                    : ''
            out.line(`hog had no stored login${which} to remove.`)
        }

        for (const { host, projectId, revoked, revokeUrl, keychainLeftover } of loggedOut) {
            const project = projectId ? `project ${projectId} on ` : ''
            out.line(`${out.style('Logged out', 'green', 'bold')} of ${project}${escapeControls(host ?? '')}.`)

            if (revoked === false) {
                out.line(
                    out.style(
                        "hog couldn't reach PostHog to revoke the login, so it keeps working in PostHog. Revoke it under Settings > Connected applications.",
                        'yellow'
                    )
                )
            }

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
