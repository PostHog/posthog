import { defineCommand } from '@/core/command'
import { escapeControls } from '@/core/output'
import { plural } from '@/core/text'
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
        'Removes the login that commands in this folder use, which is the one `hog auth status` shows. Logins to other projects stay.',
        "hog also revokes this machine's login in PostHog. Logins on other machines keep working.",
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
        const label = ({ host, projectId }: { host: string | null; projectId: string | null }): string =>
            `${projectId ? `project ${projectId} on ` : ''}${escapeControls(host ?? '')}`
        // With several logins, each warning names the login it is about.
        const about = (login: (typeof loggedOut)[number]): string => (loggedOut.length > 1 ? `${label(login)}: ` : '')

        const warnings: string[] = []
        const notes: string[] = []
        for (const login of loggedOut) {
            if (login.revoked === false) {
                warnings.push(
                    `${about(login)}hog couldn't reach PostHog to revoke the login, so it still works. Revoke it in PostHog under Settings > Connected applications.`
                )
            }
            if (login.keychainLeftover) {
                warnings.push(
                    `${about(login)}hog couldn't remove an older copy of the key from the keychain: ${login.keychainLeftover} Delete the hog item for ${escapeControls(login.host ?? '')} from the keychain.`
                )
            }
            if (login.revokeUrl) {
                notes.push(
                    out.style(
                        `${about(login)}The key keeps working until you delete it at ${escapeControls(login.revokeUrl)}`,
                        'dim'
                    )
                )
            }
        }
        if (result.stillSet.length > 0) {
            warnings.push(`Still logged in through ${result.stillSet.join(' and ')}. Unset it to log out fully.`)
        }

        if (loggedOut.length === 0) {
            const which =
                result.host && result.projectId
                    ? ` for project ${result.projectId} on ${escapeControls(result.host)}`
                    : ''
            out.report({ status: 'unchanged', result: `There's no stored login${which} to remove`, warnings })
            return
        }

        const [only] = loggedOut
        out.report({
            status: warnings.length > 0 ? 'partial' : 'done',
            result:
                only && loggedOut.length === 1
                    ? `Logged out of ${label(only)}`
                    : `Logged out of ${plural(loggedOut.length, 'login')}`,
            effects: loggedOut.length > 1 ? loggedOut.map(label) : [],
            warnings,
            notes,
        })
    },
})
