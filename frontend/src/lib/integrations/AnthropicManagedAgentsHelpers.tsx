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

function TruncationHint({
    loading,
    hasMore,
    optionCount,
    label,
}: {
    loading: boolean
    hasMore: boolean
    optionCount: number
    label: string
}): JSX.Element | null {
    if (loading || !hasMore) {
        return null
    }
    return (
        <div className="text-xs text-secondary mt-1 italic">
            Showing the first {optionCount} {label}. Refine the list in the Anthropic console if you don't see yours.
        </div>
    )
}

export function AnthropicManagedAgentPicker({ integration, value, onChange }: CommonPickerProps): JSX.Element {
    const { options, loading, hasMore } = useAnthropicManagedAgents(integration.id)

    return (
        <div>
            <LemonInputSelect
                mode="single"
                data-attr="select-anthropic-managed-agent"
                placeholder="Select an agent..."
                options={options}
                loading={loading}
                value={value ? [value] : []}
                onChange={(val) => onChange?.(val[0] ?? null)}
            />
            <TruncationHint loading={loading} hasMore={hasMore} optionCount={options.length} label="agents" />
        </div>
    )
}

export function AnthropicManagedAgentEnvironmentPicker({
    integration,
    value,
    onChange,
}: CommonPickerProps): JSX.Element {
    const { options, loading, hasMore } = useAnthropicManagedAgentEnvironments(integration.id)

    return (
        <div>
            <LemonInputSelect
                mode="single"
                data-attr="select-anthropic-managed-agent-environment"
                placeholder="Select an environment..."
                options={options}
                loading={loading}
                value={value ? [value] : []}
                onChange={(val) => onChange?.(val[0] ?? null)}
            />
            <TruncationHint loading={loading} hasMore={hasMore} optionCount={options.length} label="environments" />
        </div>
    )
}

export function AnthropicManagedAgentVaultPicker({ integration, value, onChange }: CommonPickerProps): JSX.Element {
    const { options, loading, hasMore } = useAnthropicManagedAgentVaults(integration.id)

    return (
        <div>
            <LemonInputSelect
                mode="single"
                data-attr="select-anthropic-managed-agent-vault"
                placeholder="Select a vault..."
                options={options}
                loading={loading}
                value={value ? [value] : []}
                onChange={(val) => onChange?.(val[0] ?? null)}
            />
            <TruncationHint loading={loading} hasMore={hasMore} optionCount={options.length} label="vaults" />
        </div>
    )
}

function useAnthropicManagedAgents(integrationId: number): {
    options: LemonInputSelectOption[]
    loading: boolean
    hasMore: boolean
} {
    const logic = anthropicManagedAgentsLogic({ id: integrationId })
    const { anthropicManagedAgents, anthropicManagedAgentsLoading, anthropicManagedAgentsHasMore } = useValues(logic)
    const { loadAnthropicManagedAgents } = useActions(logic)

    const options = useMemo(
        () =>
            (anthropicManagedAgents ?? []).map((a) => ({
                key: a.id,
                label: a.version ? `${a.name} (${a.version})` : a.name,
            })),
        [anthropicManagedAgents]
    )

    useEffect(() => {
        loadAnthropicManagedAgents()
    }, [loadAnthropicManagedAgents])

    return { options, loading: anthropicManagedAgentsLoading, hasMore: anthropicManagedAgentsHasMore }
}

function useAnthropicManagedAgentEnvironments(integrationId: number): {
    options: LemonInputSelectOption[]
    loading: boolean
    hasMore: boolean
} {
    const logic = anthropicManagedAgentsLogic({ id: integrationId })
    const {
        anthropicManagedAgentEnvironments,
        anthropicManagedAgentEnvironmentsLoading,
        anthropicManagedAgentEnvironmentsHasMore,
    } = useValues(logic)
    const { loadAnthropicManagedAgentEnvironments } = useActions(logic)

    const options = useMemo(
        () => (anthropicManagedAgentEnvironments ?? []).map((e) => ({ key: e.id, label: e.name })),
        [anthropicManagedAgentEnvironments]
    )

    useEffect(() => {
        loadAnthropicManagedAgentEnvironments()
    }, [loadAnthropicManagedAgentEnvironments])

    return {
        options,
        loading: anthropicManagedAgentEnvironmentsLoading,
        hasMore: anthropicManagedAgentEnvironmentsHasMore,
    }
}

function useAnthropicManagedAgentVaults(integrationId: number): {
    options: LemonInputSelectOption[]
    loading: boolean
    hasMore: boolean
} {
    const logic = anthropicManagedAgentsLogic({ id: integrationId })
    const { anthropicManagedAgentVaults, anthropicManagedAgentVaultsLoading, anthropicManagedAgentVaultsHasMore } =
        useValues(logic)
    const { loadAnthropicManagedAgentVaults } = useActions(logic)

    const options = useMemo(
        () => (anthropicManagedAgentVaults ?? []).map((v) => ({ key: v.id, label: v.display_name })),
        [anthropicManagedAgentVaults]
    )

    useEffect(() => {
        loadAnthropicManagedAgentVaults()
    }, [loadAnthropicManagedAgentVaults])

    return { options, loading: anthropicManagedAgentVaultsLoading, hasMore: anthropicManagedAgentVaultsHasMore }
}
