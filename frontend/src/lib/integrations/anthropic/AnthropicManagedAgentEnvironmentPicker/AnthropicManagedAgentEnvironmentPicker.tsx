import { useValues } from 'kea'

import { LemonInputSelect } from '@posthog/lemon-ui'

import { IntegrationType } from '~/types'

import { PickerTruncationHint } from '../PickerTruncationHint/PickerTruncationHint'
import { anthropicManagedAgentEnvironmentsLogic } from './anthropicManagedAgentEnvironmentsLogic'

type AnthropicManagedAgentEnvironmentPickerProps = {
    integration: IntegrationType
    value?: string
    onChange?: (value: string | null) => void
}

export function AnthropicManagedAgentEnvironmentPicker({
    integration,
    value,
    onChange,
}: AnthropicManagedAgentEnvironmentPickerProps): JSX.Element {
    const {
        options,
        anthropicManagedAgentEnvironmentsLoading: loading,
        showTruncationHint,
    } = useValues(anthropicManagedAgentEnvironmentsLogic({ id: integration.id }))

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
            <PickerTruncationHint show={showTruncationHint} optionCount={options.length} label="environments" />
        </div>
    )
}
