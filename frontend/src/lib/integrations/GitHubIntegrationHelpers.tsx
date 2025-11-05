import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { githubIntegrationLogic } from './githubIntegrationLogic'

export type GitHubRepositoryPickerProps = {
    integrationId: number
    value: string
    onChange: (value: string) => void
}

export const GitHubRepositoryPicker = ({
    value,
    onChange,
    integrationId,
}: GitHubRepositoryPickerProps): JSX.Element => {
    const { options, loading } = useRepositories(integrationId)

    return (
        <LemonInputSelect
            onChange={(val) => onChange?.(val[0] ?? null)}
            value={value ? [value] : []}
            mode="single"
            data-attr="select-github-repository"
            placeholder="Select a repository..."
            options={options}
            loading={loading}
        />
    )
}

export const GitHubRepositorySelectField = ({ integrationId }: { integrationId: number }): JSX.Element => {
    const { options, loading } = useRepositories(integrationId)

    return (
        <LemonField name="repositories" label="Repository">
            <LemonInputSelect
                mode="single"
                data-attr="select-github-repository"
                placeholder="Select a repository..."
                options={options}
                loading={loading}
            />
        </LemonField>
    )
}

export function useRepositories(integrationId: number): { options: LemonInputSelectOption[]; loading: boolean } {
    const logic = githubIntegrationLogic({ id: integrationId })
    const { repositories, repositoriesLoading } = useValues(logic)
    const { loadRepositories } = useActions(logic)

    useEffect(() => {
        loadRepositories()
    }, [loadRepositories])

    const options = useMemo(() => repositories.map((r) => ({ key: r, label: r })), [repositories])

    return { options, loading: repositoriesLoading }
}
