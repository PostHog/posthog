import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { githubIntegrationLogic } from 'lib/integrations/githubIntegrationLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSearchableSelect } from 'lib/lemon-ui/LemonSelect/LemonSearchableSelect'

import { sourceWizardLogic } from '../../new/sourceWizardLogic'

export function GitHubRepositorySelector(): JSX.Element {
    const { sourceConnectionDetails } = useValues(sourceWizardLogic)

    const authMethod = sourceConnectionDetails.payload?.auth_method
    const isOAuth = authMethod?.selection === 'oauth'
    const integrationId: number | undefined = authMethod?.github_integration_id

    if (isOAuth && integrationId) {
        return <GitHubRepositoryDropdown integrationId={integrationId} />
    }

    return (
        <LemonField name="repository" label="Repository">
            {({ value, onChange }) => (
                <LemonInput
                    className="ph-ignore-input"
                    data-attr="repository"
                    placeholder="owner/repo"
                    type="text"
                    value={value || ''}
                    onChange={onChange}
                    disabledReason={isOAuth ? 'Connect your GitHub integration to select from repositories' : undefined}
                />
            )}
        </LemonField>
    )
}

function GitHubRepositoryDropdown({ integrationId }: { integrationId: number }): JSX.Element {
    const { repositories, repositoriesLoading } = useValues(githubIntegrationLogic({ id: integrationId }))
    const { loadRepositories } = useActions(githubIntegrationLogic({ id: integrationId }))

    useEffect(() => {
        loadRepositories()
    }, [loadRepositories])

    return (
        <LemonField name="repository" label="Repository">
            {({ value, onChange }) => (
                <LemonSearchableSelect
                    data-attr="repository"
                    placeholder="Select a repository"
                    searchPlaceholder="Search repositories..."
                    value={value || null}
                    onChange={(newValue) => onChange(newValue ?? '')}
                    loading={repositoriesLoading}
                    options={repositories.map((repo) => ({
                        value: repo.full_name,
                        label: repo.full_name,
                    }))}
                />
            )}
        </LemonField>
    )
}
