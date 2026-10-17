import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconCheckCircle, IconHourglass, IconWarning } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import {
    GITHUB_INSTALL_PENDING_MESSAGE,
    describeGithubSetupError,
    getGithubSetupErrorCode,
} from 'lib/integrations/githubSetupErrors'
import { SceneExport } from 'scenes/sceneTypes'

import type { SSOProvider } from '~/types'

/** Path segment under {@link urls.accountConnected} — SSO link, GitHub integration, or Slack integration. */
export type AccountConnectedKind = 'github-login' | 'github-integration' | 'slack-integration' | 'invalid'

// Per-kind deep link host. GitHub already uses `posthog-code://integration`;
// Slack uses its own host so each provider's main-process handler stays isolated
// (the deep-link service registers one handler per host).
const DEEP_LINK_HOSTS: Record<Exclude<AccountConnectedKind, 'invalid'>, string> = {
    'github-login': 'posthog-code://integration',
    'github-integration': 'posthog-code://integration',
    'slack-integration': 'posthog-code://slack-integration',
}

function posthogCodeDeepUrl(
    kind: Exclude<AccountConnectedKind, 'invalid'>,
    searchParams: Record<string, unknown>
): string {
    const url = new URL(DEEP_LINK_HOSTS[kind])
    const provider = typeof searchParams.provider === 'string' ? searchParams.provider : ''
    if (provider) {
        url.searchParams.set('provider', provider)
    }
    // `integration_id` (Slack and most kinds) and `installation_id` (GitHub) are both
    // forwarded so the desktop handler can act on whichever its provider uses.
    for (const key of ['project_id', 'installation_id', 'integration_id'] as const) {
        const value = searchParams[key]
        if (value !== undefined && value !== null && value !== '') {
            url.searchParams.set(key, String(value))
        }
    }
    const errorCode = getGithubSetupErrorCode(searchParams)
    url.searchParams.set('status', errorCode ? 'error' : 'success')
    if (errorCode) {
        url.searchParams.set('error_code', errorCode)
        const errorMessage =
            (typeof searchParams.error_message === 'string' && searchParams.error_message) ||
            describeGithubSetupError(errorCode)
        url.searchParams.set('error_message', errorMessage)
    }
    return url.toString()
}

export interface AccountConnectedProps {
    kind: AccountConnectedKind
}

// Integration providers that aren't SSO providers, but render on the same page.
const INTEGRATION_LABELS: Record<string, string> = {
    slack: 'Slack',
}

function providerLabel(provider: string | undefined): string {
    if (!provider) {
        return 'Account'
    }
    return SSO_PROVIDER_NAMES[provider as SSOProvider] ?? INTEGRATION_LABELS[provider] ?? provider
}

function headline(kind: Exclude<AccountConnectedKind, 'invalid'>, label: string, isError: boolean): string {
    if (kind === 'github-integration' || kind === 'slack-integration') {
        return isError ? `${label} connection failed` : `${label} connected`
    }
    return isError ? `${label} linking failed` : `${label} linked to account`
}

function chatReturnMessage(errorCode: string, errorMessage: string | null): string {
    if (errorCode === 'github_install_pending') {
        return `${GITHUB_INSTALL_PENDING_MESSAGE} After it's approved, go back to your chat and tell the assistant to continue.`
    }
    if (errorCode) {
        return `${describeGithubSetupError(errorCode, errorMessage)} Go back to your chat and ask the assistant for a new link.`
    }
    return 'Go back to your chat and tell the assistant to continue.'
}

const VALID_KINDS: ReadonlyArray<Exclude<AccountConnectedKind, 'invalid'>> = [
    'github-login',
    'github-integration',
    'slack-integration',
]

export const scene: SceneExport<AccountConnectedProps> = {
    component: AccountConnected,
    paramsToProps: ({ params: { kind: raw } }) => {
        const kind: AccountConnectedKind = (VALID_KINDS as readonly string[]).includes(raw ?? '')
            ? (raw as AccountConnectedKind)
            : 'invalid'
        return { kind }
    },
}

/**
 * Unified return page for PostHog Desktop / web: social SSO link (`github-login`), personal GitHub
 * integration (`github-integration`), or team Slack integration (`slack-integration`). Navigates
 * to the matching `posthog-code://…` deep link so the desktop app refreshes its integrations —
 * except when started from Slack (`connect_from=slack`) or from an AI chat through the PostHog MCP
 * (`connect_from=mcp`), where it shows a terminal state and the user returns there manually.
 */
function isValidKind(kind: AccountConnectedKind | undefined): kind is Exclude<AccountConnectedKind, 'invalid'> {
    return typeof kind === 'string' && (VALID_KINDS as readonly string[]).includes(kind)
}

export function AccountConnected({ kind }: AccountConnectedProps): JSX.Element {
    const { searchParams } = useValues(router)
    const provider = typeof searchParams.provider === 'string' ? searchParams.provider : undefined
    const label = providerLabel(provider)
    const errorCode = getGithubSetupErrorCode(searchParams)
    const isError = errorCode.length > 0
    // The Slack flow has no deep link back — the user just returns to Slack themselves, so we only
    // show the success state. PostHog Desktop refreshes its integrations via a desktop deep link.
    const startedFromSlack = searchParams.connect_from === 'slack'
    // pinned: `mcp` is the `connect_from` value in the GitHub connect URL the PostHog MCP hands out.
    const startedFromChat = searchParams.connect_from === 'mcp'
    const opensDesktopApp = !startedFromSlack && !startedFromChat
    const isPending = errorCode === 'github_install_pending'
    // Allowlist-style check — `paramsToProps` is expected to map unknown kinds to `'invalid'`,
    // but guarding directly against the valid set means a route mismatch (e.g. project-prefix
    // edge case) can't crash `posthogCodeDeepUrl` with an undefined deep-link host.
    const hasValidKind = isValidKind(kind)

    useEffect(() => {
        if (hasValidKind && opensDesktopApp) {
            window.location.href = posthogCodeDeepUrl(kind, searchParams)
        }
    }, [hasValidKind, kind, searchParams, opensDesktopApp])

    if (!hasValidKind) {
        return (
            <BridgePage view="account-connected">
                <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                    <p className="text-muted mb-0">
                        This link is not valid. Return to PostHog from the product you started from.
                    </p>
                </div>
            </BridgePage>
        )
    }

    const showLoginLine = kind === 'github-login' && !isError

    return (
        <BridgePage view="account-connected">
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                {startedFromChat && isPending ? (
                    <IconHourglass className="text-warning text-5xl shrink-0" />
                ) : isError ? (
                    <IconWarning className="text-danger text-5xl shrink-0" />
                ) : (
                    <IconCheckCircle className="text-success text-5xl shrink-0" />
                )}
                <h2 className="text-xl font-semibold m-0">
                    {startedFromChat && isPending ? `${label} install needs approval` : headline(kind, label, isError)}
                </h2>
                {showLoginLine && <p className="text-muted mb-0">You can now log into PostHog using {label}.</p>}
                {startedFromChat ? (
                    <p className="text-muted mb-0">
                        {chatReturnMessage(
                            errorCode,
                            typeof searchParams.error_message === 'string' ? searchParams.error_message : null
                        )}
                    </p>
                ) : startedFromSlack ? (
                    <p className="text-muted mb-0">
                        {isError
                            ? 'Something went wrong. Head back to Slack and try again.'
                            : 'You can head back to Slack now.'}
                    </p>
                ) : (
                    <p className="text-muted mb-0">
                        <strong>Returning to PostHog Desktop…</strong>
                        <br />
                        <em>If this hasn't happened automatically, get back to the PostHog Desktop app manually.</em>
                    </p>
                )}
            </div>
        </BridgePage>
    )
}
