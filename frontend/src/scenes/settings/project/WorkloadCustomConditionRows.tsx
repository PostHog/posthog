import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { CUSTOM_CONDITION, type WorkloadConditionRow } from './workloadConditionPresets'
import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'

export function WorkloadCustomConditionRows(): JSX.Element {
    const { conditionRows } = useValues(workloadTrustPoliciesLogic)
    const { setConditionRows } = useActions(workloadTrustPoliciesLogic)

    const update = (index: number, row: WorkloadConditionRow): void =>
        setConditionRows(conditionRows.map((current, at) => (at === index ? row : current)))

    return (
        <div className="flex flex-col gap-2 w-full">
            {conditionRows.map((row, index) => (
                <div key={index} className="flex flex-wrap gap-2 items-start">
                    <LemonInput
                        value={row.claim ?? ''}
                        onChange={(claim) => update(index, { ...row, claim })}
                        placeholder="Claim, like environment"
                        className="min-w-40 flex-1"
                        data-attr="workload-trust-policy-custom-condition-claim"
                    />
                    <LemonInput
                        value={row.value}
                        onChange={(value) => update(index, { ...row, value })}
                        placeholder="Exact value, like production"
                        className="min-w-40 flex-1"
                        data-attr="workload-trust-policy-condition-value"
                    />
                    <LemonButton
                        icon={<IconTrash />}
                        tooltip="Remove this condition"
                        onClick={() => setConditionRows(conditionRows.filter((_, at) => at !== index))}
                        data-attr="workload-trust-policy-condition-remove"
                    />
                </div>
            ))}
            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    onClick={() =>
                        setConditionRows([...conditionRows, { preset: CUSTOM_CONDITION, claim: '', value: '' }])
                    }
                    data-attr="workload-trust-policy-condition-add"
                >
                    Add condition
                </LemonButton>
            </div>
        </div>
    )
}
