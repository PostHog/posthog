import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

import { anthropicManagedAgentsLogic } from './anthropicManagedAgentsLogic'

type CommonPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
}

export function AnthropicManagedAgentPicker({ integration, value, onChange }: CommonPickerProps): JSX.Element {
    const { options, loading } = useAnthropicManagedAgents(integration.id)

    return (
        <LemonInputSelect
            mode="single"
            data-attr="select-anthropic-managed-agent"
            placeholder="Select an agent..."
            options={options}
            loading={loading}
            value={value ? [value] : []}
            onChange={(val) => onChange?.(val[0] ?? null)}
        />
    )
}

export function AnthropicManagedAgentEnvironmentPicker({
    integration,
    value,
    onChange,
}: CommonPickerProps): JSX.Element {
    const { options, loading } = useAnthropicManagedAgentEnvironments(integration.id)

    return (
        <LemonInputSelect
            mode="single"
            data-attr="select-anthropic-managed-agent-environment"
            placeholder="Select an environment..."
            options={options}
            loading={loading}
            value={value ? [value] : []}
            onChange={(val) => onChange?.(val[0] ?? null)}
        />
    )
}

export function AnthropicManagedAgentVaultPicker({ integration, value, onChange }: CommonPickerProps): JSX.Element {
    const { options, loading } = useAnthropicManagedAgentVaults(integration.id)

    return (
        <LemonInputSelect
            mode="single"
            data-attr="select-anthropic-managed-agent-vault"
            placeholder="Select a vault..."
            options={options}
            loading={loading}
            value={value ? [value] : []}
            onChange={(val) => onChange?.(val[0] ?? null)}
        />
    )
}

function useAnthropicManagedAgents(integrationId: number): { options: LemonInputSelectOption[]; loading: boolean } {
    const logic = anthropicManagedAgentsLogic({ id: integrationId })
    const { anthropicManagedAgents, anthropicManagedAgentsLoading } = useValues(logic)
    const { loadAnthropicManagedAgents } = useActions(logic)

    const options = useMemo(
        () =>
            anthropicManagedAgents.map((a) => ({
                key: a.id,
                label: a.version ? `${a.name} (${a.version})` : a.name,
            })),
        [anthropicManagedAgents]
    )

    useEffect(() => {
        loadAnthropicManagedAgents()
    }, [loadAnthropicManagedAgents])

    return { options, loading: anthropicManagedAgentsLoading }
}

function useAnthropicManagedAgentEnvironments(integrationId: number): {
    options: LemonInputSelectOption[]
    loading: boolean
} {
    const logic = anthropicManagedAgentsLogic({ id: integrationId })
    const { anthropicManagedAgentEnvironments, anthropicManagedAgentEnvironmentsLoading } = useValues(logic)
    const { loadAnthropicManagedAgentEnvironments } = useActions(logic)

    const options = useMemo(
        () => anthropicManagedAgentEnvironments.map((e) => ({ key: e.id, label: e.name })),
        [anthropicManagedAgentEnvironments]
    )

    useEffect(() => {
        loadAnthropicManagedAgentEnvironments()
    }, [loadAnthropicManagedAgentEnvironments])

    return { options, loading: anthropicManagedAgentEnvironmentsLoading }
}

function useAnthropicManagedAgentVaults(integrationId: number): {
    options: LemonInputSelectOption[]
    loading: boolean
} {
    const logic = anthropicManagedAgentsLogic({ id: integrationId })
    const { anthropicManagedAgentVaults, anthropicManagedAgentVaultsLoading } = useValues(logic)
    const { loadAnthropicManagedAgentVaults } = useActions(logic)

    const options = useMemo(
        () => anthropicManagedAgentVaults.map((v) => ({ key: v.id, label: v.display_name })),
        [anthropicManagedAgentVaults]
    )

    useEffect(() => {
        loadAnthropicManagedAgentVaults()
    }, [loadAnthropicManagedAgentVaults])

    return { options, loading: anthropicManagedAgentVaultsLoading }
}
