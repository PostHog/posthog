export const GITHUB_INSTALL_PENDING_MESSAGE =
    'Your request to connect to GitHub has been sent to the organization owners. They will need to complete the installation.'

export const GITHUB_SETUP_ERROR_MESSAGES: Record<string, string> = {
    access_denied: 'GitHub authorization was canceled.',
    github_oauth_error: 'GitHub rejected the authorization. Please try again.',
    missing_params: "GitHub didn't send back the expected parameters. Please try again.",
    invalid_state: 'The GitHub setup request expired or could not be verified. Please try again.',
    invalid_team: 'Your project access changed during setup. Please try again.',
    invalid_installation_id: 'GitHub returned an invalid installation. Please try again.',
    exchange_failed: 'GitHub rejected the authorization code. Please try again.',
    installation_verify_failed: 'Could not verify your access to this GitHub installation. Please try again.',
    installation_not_authorized:
        "Your GitHub account isn't authorized for this installation. Ask the org admin to grant access, or sign in with a different GitHub account.",
    installation_fetch_failed: 'Could not fetch installation details from GitHub. Please try again.',
    installation_token_failed: 'Could not get an access token from GitHub. Please try again.',
    integration_create_failed: 'Could not save the GitHub connection. Please try again.',
    github_install_failed: 'Could not connect GitHub. Please try again.',
}

export function normalizeGithubOAuthCallbackError(githubError: string): string {
    return githubError === 'access_denied' ? 'access_denied' : 'github_oauth_error'
}

export function getGithubSetupErrorCode(searchParams: Record<string, unknown>): string {
    return (
        (typeof searchParams.error === 'string' && searchParams.error) ||
        (typeof searchParams.github_setup_error === 'string' && searchParams.github_setup_error) ||
        ''
    )
}

export function describeGithubSetupError(code: string | null, detail: string | null = null): string {
    if (code && GITHUB_SETUP_ERROR_MESSAGES[code]) {
        return GITHUB_SETUP_ERROR_MESSAGES[code]
    }
    if (detail) {
        return detail
    }
    return GITHUB_SETUP_ERROR_MESSAGES.github_install_failed
}

const GITHUB_LINK_ERROR_OVERRIDES: Record<string, string> = {
    invalid_state: 'The GitHub link request expired or could not be verified. Please try again.',
    exchange_failed: 'GitHub rejected the authorization code. Check that the GitHub App is configured correctly.',
}

export function describeGithubLinkError(code: string | null): string {
    if (code && GITHUB_LINK_ERROR_OVERRIDES[code]) {
        return GITHUB_LINK_ERROR_OVERRIDES[code]
    }
    return describeGithubSetupError(code)
}
