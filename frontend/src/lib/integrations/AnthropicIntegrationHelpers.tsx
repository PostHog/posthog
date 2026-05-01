import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

import { anthropicIntegrationLogic } from './anthropicIntegrationLogic'

type CommonPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
}

export function AnthropicAgentPicker({ integration, value, onChange }: CommonPickerProps): JSX.Element {
    const { options, loading } = useAnthropicAgents(integration.id)

    return (
        <LemonInputSelect
            mode="single"
            data-attr="select-anthropic-agent"
            placeholder="Select an agent..."
            options={options}
            loading={loading}
            value={value ? [value] : []}
            onChange={(val) => onChange?.(val[0] ?? null)}
        />
    )
}

export function AnthropicEnvironmentPicker({ integration, value, onChange }: CommonPickerProps): JSX.Element {
    const { options, loading } = useAnthropicEnvironments(integration.id)

    return (
        <LemonInputSelect
            mode="single"
            data-attr="select-anthropic-environment"
            placeholder="Select an environment..."
            options={options}
            loading={loading}
            value={value ? [value] : []}
            onChange={(val) => onChange?.(val[0] ?? null)}
        />
    )
}

export function AnthropicVaultPicker({ integration, value, onChange }: CommonPickerProps): JSX.Element {
    const { options, loading } = useAnthropicVaults(integration.id)

    return (
        <LemonInputSelect
            mode="single"
            data-attr="select-anthropic-vault"
            placeholder="Select a vault..."
            options={options}
            loading={loading}
            value={value ? [value] : []}
            onChange={(val) => onChange?.(val[0] ?? null)}
        />
    )
}

function useAnthropicAgents(integrationId: number): { options: LemonInputSelectOption[]; loading: boolean } {
    const logic = anthropicIntegrationLogic({ id: integrationId })
    const { anthropicAgents, anthropicAgentsLoading } = useValues(logic)
    const { loadAnthropicAgents } = useActions(logic)

    const options = useMemo(
        () =>
            anthropicAgents.map((a) => ({
                key: a.id,
                label: a.version ? `${a.name} (${a.version})` : a.name,
            })),
        [anthropicAgents]
    )

    useEffect(() => {
        loadAnthropicAgents()
    }, [loadAnthropicAgents])

    return { options, loading: anthropicAgentsLoading }
}

function useAnthropicEnvironments(integrationId: number): { options: LemonInputSelectOption[]; loading: boolean } {
    const logic = anthropicIntegrationLogic({ id: integrationId })
    const { anthropicEnvironments, anthropicEnvironmentsLoading } = useValues(logic)
    const { loadAnthropicEnvironments } = useActions(logic)

    const options = useMemo(
        () => anthropicEnvironments.map((e) => ({ key: e.id, label: e.name })),
        [anthropicEnvironments]
    )

    useEffect(() => {
        loadAnthropicEnvironments()
    }, [loadAnthropicEnvironments])

    return { options, loading: anthropicEnvironmentsLoading }
}

function useAnthropicVaults(integrationId: number): { options: LemonInputSelectOption[]; loading: boolean } {
    const logic = anthropicIntegrationLogic({ id: integrationId })
    const { anthropicVaults, anthropicVaultsLoading } = useValues(logic)
    const { loadAnthropicVaults } = useActions(logic)

    const options = useMemo(() => anthropicVaults.map((v) => ({ key: v.id, label: v.display_name })), [anthropicVaults])

    useEffect(() => {
        loadAnthropicVaults()
    }, [loadAnthropicVaults])

    return { options, loading: anthropicVaultsLoading }
}
