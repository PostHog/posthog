import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { CUSTOM_CONDITION, rowForPreset, type WorkloadConditionRow } from './workloadConditionPresets'
import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'

const CUSTOM_PREFIX = `${CUSTOM_CONDITION}:`

// A custom row picks one claim, so the select offers each claim as its own option.
function selectValue(row: WorkloadConditionRow): string {
    return row.preset === CUSTOM_CONDITION ? `${CUSTOM_PREFIX}${row.claim ?? ''}` : row.preset
}

export function WorkloadConditionRows(): JSX.Element {
    const { conditionRows, editingProvider } = useValues(workloadTrustPoliciesLogic)
    const { setConditionRows } = useActions(workloadTrustPoliciesLogic)

    const presets = editingProvider?.condition_presets ?? []
    const claims = editingProvider?.condition_claims ?? []
    // A stored condition on a claim the provider no longer offers still shows, so it can be removed.
    const retired = conditionRows
        .filter((row) => row.preset === CUSTOM_CONDITION && !claims.some((claim) => claim.name === row.claim))
        .map((row) => ({ value: selectValue(row), label: row.claim ?? '' }))
    const options = [
        { title: 'Common choices', options: presets.map((preset) => ({ value: preset.key, label: preset.label })) },
        {
            title: 'One claim of the token',
            options: [
                ...claims.map((claim) => ({ value: `${CUSTOM_PREFIX}${claim.name}`, label: claim.label })),
                ...retired,
            ],
        },
    ]

    const update = (index: number, row: WorkloadConditionRow): void =>
        setConditionRows(conditionRows.map((current, at) => (at === index ? row : current)))
    const choose = (index: number, value: string): void => {
        const preset = presets.find((candidate) => candidate.key === value)
        update(
            index,
            preset
                ? rowForPreset(preset)
                : { preset: CUSTOM_CONDITION, claim: value.slice(CUSTOM_PREFIX.length), value: '' }
        )
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            {conditionRows.map((row, index) => {
                const preset = presets.find((candidate) => candidate.key === row.preset)
                const claim = claims.find((candidate) => candidate.name === row.claim)
                const takesValue = preset ? preset.takes_value : true
                return (
                    <div key={index} className="flex flex-col gap-1">
                        <div className="flex flex-wrap gap-2 items-start">
                            <LemonSelect
                                value={selectValue(row)}
                                onChange={(value) => choose(index, value)}
                                options={options}
                                className="min-w-60 flex-1"
                                data-attr="workload-trust-policy-condition-preset"
                            />
                            {takesValue ? (
                                <LemonInput
                                    value={row.value}
                                    onChange={(value) => update(index, { ...row, value })}
                                    placeholder={preset?.placeholder || claim?.placeholder || undefined}
                                    className="min-w-40 flex-1"
                                    data-attr="workload-trust-policy-condition-value"
                                />
                            ) : null}
                            <LemonButton
                                icon={<IconTrash />}
                                tooltip="Remove this condition"
                                onClick={() => setConditionRows(conditionRows.filter((_, at) => at !== index))}
                                data-attr="workload-trust-policy-condition-remove"
                            />
                        </div>
                        <div className="text-secondary text-xs">
                            {preset?.help_text ||
                                claim?.help_text ||
                                (preset || claim
                                    ? ''
                                    : "PostHog doesn't support this condition anymore. Remove it to save.")}
                        </div>
                    </div>
                )
            })}
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() =>
                        setConditionRows([
                            ...conditionRows,
                            presets[0]
                                ? rowForPreset(presets[0])
                                : { preset: CUSTOM_CONDITION, claim: claims[0]?.name, value: '' },
                        ])
                    }
                    data-attr="workload-trust-policy-condition-add"
                >
                    Add condition
                </LemonButton>
            </div>
        </div>
    )
}
