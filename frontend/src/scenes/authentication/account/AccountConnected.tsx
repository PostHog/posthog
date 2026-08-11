import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconCheckCircle, IconHourglass, IconWarning } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { SSO_PROVIDER_NAMES } from 'lib/constants'
import {
    describeGithubSetupError,
    getGithubSetupErrorCode,
    isGithubInstallPending,
} from 'lib/integrations/githubSetupErrors'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { SSOProvider } from '~/types'

type ConnectStatus = 'success' | 'error' | 'pending'

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

export function resolveConnectStatus(searchParams: Record<string, unknown>): ConnectStatus {
    const errorCode = getGithubSetupErrorCode(searchParams)
    if (isGithubInstallPending(errorCode)) {
        return 'pending'
    }
    return errorCode.length > 0 ? 'error' : 'success'
}

export function headline(kind: Exclude<AccountConnectedKind, 'invalid'>, label: string, status: ConnectStatus): string {
    if (status === 'pending') {
        return `${label} installation waiting for approval`
    }
    if (kind === 'github-integration' || kind === 'slack-integration') {
        return status === 'error' ? `${label} connection failed` : `${label} connected`
    }
    return status === 'error' ? `${label} linking failed` : `${label} linked to account`
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
 * except when started from Slack (`connect_from=slack`), where it shows a terminal success state
 * and the user returns to Slack manually (no deep link).
 */
function isValidKind(kind: AccountConnectedKind | undefined): kind is Exclude<AccountConnectedKind, 'invalid'> {
    return typeof kind === 'string' && (VALID_KINDS as readonly string[]).includes(kind)
}

export function AccountConnected({ kind }: AccountConnectedProps): JSX.Element {
    const { searchParams } = useValues(router)
    const provider = typeof searchParams.provider === 'string' ? searchParams.provider : undefined
    const label = providerLabel(provider)
    const errorCode = getGithubSetupErrorCode(searchParams)
    // An install awaiting org-owner approval shares the error code path, so `resolveConnectStatus`
    // splits it back out into its own waiting state rather than a hard failure.
    const status = resolveConnectStatus(searchParams)
    const isPending = status === 'pending'
    // kea-router decodes a numeric `project_id=2` to the number `2`, so coerce whatever type arrives
    // (the same handling `posthogCodeDeepUrl` applies) instead of gating on `typeof === 'string'`.
    const projectIdParam = searchParams.project_id
    const projectId =
        projectIdParam !== undefined && projectIdParam !== null && projectIdParam !== ''
            ? String(projectIdParam)
            : undefined
    // The Slack flow has no deep link back — the user just returns to Slack themselves, so we only
    // show the success state. PostHog Desktop refreshes its integrations via a desktop deep link.
    const startedFromSlack = searchParams.connect_from === 'slack'
    // Allowlist-style check — `paramsToProps` is expected to map unknown kinds to `'invalid'`,
    // but guarding directly against the valid set means a route mismatch (e.g. project-prefix
    // edge case) can't crash `posthogCodeDeepUrl` with an undefined deep-link host.
    const hasValidKind = isValidKind(kind)

    useEffect(() => {
        if (hasValidKind && !startedFromSlack) {
            window.location.href = posthogCodeDeepUrl(kind, searchParams)
        }
    }, [hasValidKind, kind, searchParams, startedFromSlack])

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

    const showLoginLine = kind === 'github-login' && status === 'success'

    return (
        <BridgePage view="account-connected">
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                {status === 'error' ? (
                    <IconWarning className="text-danger text-5xl shrink-0" />
                ) : status === 'pending' ? (
                    <IconHourglass className="text-muted text-5xl shrink-0" />
                ) : (
                    <IconCheckCircle className="text-success text-5xl shrink-0" />
                )}
                <h2 className="text-xl font-semibold m-0">{headline(kind, label, status)}</h2>
                {showLoginLine && <p className="text-muted mb-0">You can now log into PostHog using {label}.</p>}
                {/* Show the real reason on every flow — before this it only reached the desktop deep link. */}
                {isPending && <p className="text-muted mb-0">{describeGithubSetupError(errorCode)}</p>}
                {startedFromSlack ? (
                    <>
                        <p className="text-muted mb-0">{slackReturnLine(status)}</p>
                        {projectId && (
                            <LemonButton type="primary" to={urls.project(projectId)}>
                                Continue to PostHog
                            </LemonButton>
                        )}
                    </>
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

function slackReturnLine(status: ConnectStatus): string {
    if (status === 'pending') {
        return "Head back to Slack. We'll finish connecting GitHub once an owner approves the install."
    }
    if (status === 'error') {
        return 'Something went wrong. Head back to Slack and try again.'
    }
    return 'You can head back to Slack now.'
}
