import { useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

import { PickerTruncationHint } from '../PickerTruncationHint/PickerTruncationHint'
import { anthropicManagedAgentVaultsLogic } from './anthropicManagedAgentVaultsLogic'

type AnthropicManagedAgentVaultPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
}

export function AnthropicManagedAgentVaultPicker({
    integration,
    value,
    onChange,
}: AnthropicManagedAgentVaultPickerProps): JSX.Element {
    const {
        options,
        anthropicManagedAgentVaultsLoading: loading,
        showTruncationHint,
    } = useValues(anthropicManagedAgentVaultsLogic({ id: integration.id }))

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
            <PickerTruncationHint show={showTruncationHint} optionCount={options.length} label="vaults" />
        </div>
    )
}
