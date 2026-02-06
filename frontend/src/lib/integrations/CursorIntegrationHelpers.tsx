import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSelect, Spinner } from '@posthog/lemon-ui'

import { cursorIntegrationLogic } from './cursorIntegrationLogic'

export type CursorRepositoryPickerProps = {
    integrationId: number
    value: string
    onChange: (value: string) => void
}

export function CursorRepositoryPicker({ value, onChange, integrationId }: CursorRepositoryPickerProps): JSX.Element {
    const logic = cursorIntegrationLogic({ id: integrationId })
    const { repositories, repositoriesLoading } = useValues(logic)
    const { loadRepositories } = useActions(logic)

    useEffect(() => {
        loadRepositories()
    }, [loadRepositories, integrationId])

    if (repositoriesLoading) {
        return <Spinner className="size-6" />
    }

    const options = repositories.map((r: { name: string; url: string }) => ({
        value: r.url,
        label: r.name,
    }))

    return (
        <LemonSelect
            value={value || null}
            onSelect={(url) => onChange?.(url ?? '')}
            options={options}
            placeholder="Select a repository..."
            allowClear
            fullWidth
            size="small"
            data-attr="select-cursor-repository"
        />
    )
}
