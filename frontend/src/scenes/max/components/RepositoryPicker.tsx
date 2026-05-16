import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconGithub, IconX } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { useRepositories } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { maxThreadLogic } from '../maxThreadLogic'

const SANDBOX_NO_REPO_VALUE = '__sandbox_no_repo__'

export function RepositoryPicker(): JSX.Element | null {
    const { selectedRepository, contextDisabledReason, shouldAttachSandboxRepository, isSandboxEnabled, conversation } =
        useValues(maxThreadLogic)
    const { setSelectedRepository } = useActions(maxThreadLogic)
    const { integrations, integrationsLoading } = useValues(integrationsLogic)

    const githubIntegration = useMemo(() => integrations?.find((i) => i.kind === 'github'), [integrations])

    if (integrationsLoading || !githubIntegration) {
        return null
    }

    const repositoryLocked = isSandboxEnabled && !shouldAttachSandboxRepository

    const repoLockedReason = repositoryLocked
        ? 'Repository is fixed for this thread. Start a new thread to use a different repo.'
        : null

    return (
        <RepositoryPickerInner
            integrationId={githubIntegration.id}
            selectedRepository={selectedRepository}
            onSelect={setSelectedRepository}
            disabledReason={contextDisabledReason ?? repoLockedReason}
            allowClear={shouldAttachSandboxRepository}
            repositoryLocked={repositoryLocked}
            sandboxRepositoryFromTask={conversation?.sandbox_repository ?? null}
        />
    )
}

function RepositoryPickerInner({
    integrationId,
    selectedRepository,
    onSelect,
    disabledReason,
    allowClear,
    repositoryLocked,
    sandboxRepositoryFromTask,
}: {
    integrationId: number
    selectedRepository: string | null
    onSelect: (repository: string | null) => void
    disabledReason: string | null
    allowClear: boolean
    repositoryLocked: boolean
    sandboxRepositoryFromTask: string | null
}): JSX.Element {
    const { options, loading } = useRepositories(integrationId)

    const lockedSlug = (repositoryLocked ? (sandboxRepositoryFromTask ?? selectedRepository ?? '') : '').trim()
    const lockedValue = lockedSlug || SANDBOX_NO_REPO_VALUE
    const lockedLabel = lockedSlug || 'No repository'

    const selectOptions = useMemo(() => {
        if (repositoryLocked) {
            return [{ value: lockedValue, label: lockedLabel }]
        }
        return options.map((o) => ({ value: o.label, label: o.label }))
    }, [repositoryLocked, lockedValue, lockedLabel, options])

    const selectValue = repositoryLocked ? lockedValue : (selectedRepository ?? undefined)

    return (
        <span className="flex items-center gap-0.5">
            <LemonSelect
                value={selectValue}
                onChange={(value) => {
                    if (repositoryLocked) {
                        return
                    }
                    onSelect(value)
                }}
                options={selectOptions}
                size="xxsmall"
                type="tertiary"
                icon={<IconGithub className="text-secondary" />}
                placeholder="Choose a repository"
                disabledReason={disabledReason}
                dropdownPlacement="top-start"
                dropdownMatchSelectWidth={false}
                className="flex-shrink-0 border [&>span]:text-secondary"
                loading={repositoryLocked ? false : loading}
            />
            {allowClear && selectedRepository && (
                <LemonButton
                    size="xxsmall"
                    type="tertiary"
                    icon={<IconX />}
                    onClick={() => onSelect(null)}
                    tooltip="Remove repository"
                />
            )}
        </span>
    )
}
