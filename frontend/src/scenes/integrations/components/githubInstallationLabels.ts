import type { GitHubAvailableInstallationApi } from 'products/integrations/frontend/generated/api.schemas'

// The GitHub account name is what a person recognizes, so it carries the label wherever we have
// it. The id is a fallback for an installation whose account metadata never arrived.
export function accountLabel(installation: GitHubAvailableInstallationApi): string {
    return installation.account_name || `installation ${installation.installation_id}`
}

// Where an entry came from decides whether an unfamiliar account reads as a teammate's work or as a
// stranger in your settings, so every entry says its source.
export function sourceLabel(installation: GitHubAvailableInstallationApi, personalGithubLogin?: string | null): string {
    return installation.source_team_id !== null
        ? `Connected to ${installation.source_team_name ?? `project ${installation.source_team_id}`}`
        : `Found through your GitHub connection${personalGithubLogin ? ` as ${personalGithubLogin}` : ''}`
}
