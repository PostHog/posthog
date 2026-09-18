export type GitHubDisconnectScope = 'project' | 'account'

/**
 * Backend rule: disconnecting the last reference to a GitHub App installation also uninstalls the
 * App on GitHub and removes every other PostHog link to it, so the dialog has to say which case
 * the user is in rather than the generic "this cannot be undone".
 */
export function buildGithubDisconnectDescription(
    accountName: string,
    installationShared: boolean,
    scope: GitHubDisconnectScope = 'project'
): string {
    if (installationShared) {
        const subject = scope === 'account' ? 'Your account stops using GitHub.' : 'This project stops using GitHub.'
        return `${subject} The PostHog app stays installed on GitHub because other projects or accounts still use it.`
    }
    return `This uninstalls the PostHog app from ${accountName} on GitHub and disconnects it from every PostHog project and personal account that uses it.`
}
