import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonInputSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { githubIntegrationLogic } from 'lib/integrations/githubIntegrationLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { IntegrationType } from '~/types'

import { experimentsConfigLogic } from './experimentsConfigLogic'

// Must pick the same integration as the backend's resolve_team_github_integration (org accounts
// first, then oldest; broken installs skipped), or the dropdown offers repositories the
// server-side validation then rejects.
function resolveCleanupIntegration(integrations: IntegrationType[]): IntegrationType | undefined {
    return integrations
        .filter(
            (integration) =>
                integration.errors !== 'TOKEN_REFRESH_FAILED' && !integration.config?.installation_unavailable_since
        )
        .sort(
            (a, b) =>
                // Missing account type sorts last, like Postgres NULLS LAST.
                (a.config?.account?.type ?? '\uffff').localeCompare(b.config?.account?.type ?? '\uffff') ||
                a.created_at.localeCompare(b.created_at) ||
                a.id - b.id
        )[0]
}

export function FlagCleanupRepository(): JSX.Element {
    const { experimentsConfig, experimentsConfigUpdating } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)
    const { githubIntegrations, integrationsLoading } = useValues(integrationsLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedValue = experimentsConfig?.flag_cleanup_repository ?? null
    const integration = resolveCleanupIntegration(githubIntegrations)

    if (!integration) {
        if (integrationsLoading) {
            return (
                <div className="max-w-160">
                    <LemonInputSelect mode="single" options={[]} loading placeholder="Select a repository" />
                </div>
            )
        }
        return (
            <div className="flex items-center gap-2 max-w-160">
                <p className="mb-0 text-secondary">Connect GitHub in your project settings to choose a repository.</p>
                {savedValue !== null && (
                    <LemonButton
                        type="secondary"
                        onClick={() => updateExperimentsConfig({ flag_cleanup_repository: null })}
                        loading={experimentsConfigUpdating}
                        disabledReason={restrictionReason}
                    >
                        Clear
                    </LemonButton>
                )}
            </div>
        )
    }

    return (
        <RepositoryPicker
            integrationId={integration.id}
            value={savedValue}
            updating={experimentsConfigUpdating}
            restrictionReason={restrictionReason}
            onChange={(repository) => updateExperimentsConfig({ flag_cleanup_repository: repository })}
        />
    )
}

// Separate component so githubIntegrationLogic only mounts once an integration id exists.
function RepositoryPicker({
    integrationId,
    value,
    updating,
    restrictionReason,
    onChange,
}: {
    integrationId: number
    value: string | null
    updating: boolean
    restrictionReason: string | null
    onChange: (repository: string | null) => void
}): JSX.Element {
    const logic = githubIntegrationLogic({ id: integrationId })
    const { repositories, repositoriesLoading } = useValues(logic)
    const { loadRepositories } = useActions(logic)

    useEffect(() => {
        loadRepositories()
    }, [loadRepositories])

    const options = repositories.map((repo) => ({ key: repo.full_name, label: repo.full_name }))
    // A saved default can predate the current repository cache; keep it visible in the control.
    if (value && !options.some((option) => option.key === value)) {
        options.push({ key: value, label: value })
    }

    return (
        <div className="flex items-center gap-2 max-w-160">
            <LemonInputSelect
                mode="single"
                value={value ? [value] : []}
                onChange={(selected) => selected[0] && selected[0] !== value && onChange(selected[0])}
                options={options}
                loading={repositoriesLoading || updating}
                disabledReason={restrictionReason ?? undefined}
                placeholder="Select a repository"
                data-attr="experiment-flag-cleanup-default-repository"
                className="flex-1"
            />
            {value !== null && (
                <LemonButton
                    type="secondary"
                    onClick={() => onChange(null)}
                    loading={updating}
                    disabledReason={restrictionReason}
                >
                    Clear
                </LemonButton>
            )}
        </div>
    )
}
