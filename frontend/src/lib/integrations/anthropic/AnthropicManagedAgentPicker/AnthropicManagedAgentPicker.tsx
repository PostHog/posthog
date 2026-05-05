import { useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

import { PickerTruncationHint } from '../PickerTruncationHint/PickerTruncationHint'
import { anthropicManagedAgentsLogic } from './anthropicManagedAgentsLogic'

type AnthropicManagedAgentPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
}

export function AnthropicManagedAgentPicker({
    integration,
    value,
    onChange,
}: AnthropicManagedAgentPickerProps): JSX.Element {
    const {
        options,
        anthropicManagedAgentsLoading: loading,
        showTruncationHint,
    } = useValues(anthropicManagedAgentsLogic({ id: integration.id }))

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
            <PickerTruncationHint show={showTruncationHint} optionCount={options.length} label="agents" />
        </div>
    )
}
