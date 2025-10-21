import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { gitlabIntegrationLogic } from './gitlabIntegrationLogic'

export type GitLabProjectPickerProps = {
    integrationId: number
    value: string
    onChange: (value: string) => void
}

export const GitLabProjectPicker = ({ value, onChange, integrationId }: GitLabProjectPickerProps): JSX.Element => {
    const { options, loading } = useProjects(integrationId)

    return (
        <LemonInputSelect
            onChange={(val) => onChange?.(val[0] ?? null)}
            value={value ? [value] : []}
            mode="single"
            data-attr="select-gitlab-project"
            placeholder="Select a project..."
            options={options}
            loading={loading}
        />
    )
}

export const GitLabProjectSelectField = ({ integrationId }: { integrationId: number }): JSX.Element => {
    const { options, loading } = useProjects(integrationId)

    return (
        <LemonField name="projects" label="Project">
            <LemonInputSelect
                mode="single"
                data-attr="select-gitlab-project"
                placeholder="Select a project..."
                options={options}
                loading={loading}
            />
        </LemonField>
    )
}

export function useProjects(integrationId: number): { options: LemonInputSelectOption[]; loading: boolean } {
    const logic = gitlabIntegrationLogic({ id: integrationId })
    const { projects, projectsLoading } = useValues(logic)
    const { loadProjects } = useActions(logic)

    useEffect(() => {
        loadProjects()
    }, [loadProjects])

    const options = useMemo(() => projects.map((r) => ({ key: r, label: r })), [projects])

    return { options, loading: projectsLoading }
}
