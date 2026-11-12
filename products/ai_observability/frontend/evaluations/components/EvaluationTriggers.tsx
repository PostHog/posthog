import { useActions, useValues } from 'kea'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { pluralize } from 'lib/utils/strings'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationConditionSet, EvaluationTarget } from '../types'

interface EvaluationTriggersProps {
    conditions?: EvaluationConditionSet[]
    onChange?: (conditions: EvaluationConditionSet[]) => void
    /** The unit the sampling percentage applies to. The configuration editor describes the
     * evaluation's own target, so it leaves this unset. The backfill editor passes the unit the
     * server counted, which is still the saved target after an unsaved target edit. */
    unit?: EvaluationTarget
}

export function EvaluationTriggers({ conditions, onChange, unit }: EvaluationTriggersProps = {}): JSX.Element {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setTriggerConditions } = useActions(llmEvaluationLogic)

    if (!evaluation) {
        return <div>Loading...</div>
    }

    const current = conditions ?? evaluation.conditions
    const update = onChange ?? setTriggerConditions

    const addConditionSet = (): void => {
        const newCondition: EvaluationConditionSet = {
            id: `cond-${Date.now()}`,
            rollout_percentage: 100,
            properties: [],
        }
        update([...current, newCondition])
    }

    const updateConditionSet = (index: number, updates: Partial<EvaluationConditionSet>): void => {
        const updatedConditions = current.map((condition, i) =>
            i === index ? { ...condition, ...updates } : condition
        )
        update(updatedConditions)
    }

    const removeConditionSet = (index: number): void => {
        if (current.length === 1) {
            // Keep at least one condition set
            return
        }
        const updatedConditions = current.filter((_, i) => i !== index)
        update(updatedConditions)
    }

    const duplicateConditionSet = (index: number): void => {
        const conditionToDuplicate = current[index]
        const duplicatedCondition: EvaluationConditionSet = {
            ...conditionToDuplicate,
            id: `cond-${Date.now()}`,
        }
        const updatedConditions = [...current]
        updatedConditions.splice(index + 1, 0, duplicatedCondition)
        update(updatedConditions)
    }

    const unitPlural = pluralize(2, unit ?? evaluation.target, undefined, false)

    return (
        <div className="flex flex-col gap-1">
            {current.map((condition, index) => {
                const percentageValue = condition.rollout_percentage || 0
                const hasFilters = (condition.properties ?? []).length > 0

                return (
                    <div key={condition.id} className="flex flex-col gap-1">
                        <div className="flex items-start gap-2" data-attr="llma-evaluation-condition-set">
                            <div className="flex flex-wrap items-center gap-2 text-sm min-w-0 flex-1">
                                {/* Fixed width, so the inputs of every set line up under each other. */}
                                <span className="w-12 shrink-0 text-secondary">{index === 0 ? 'Run on' : 'or'}</span>
                                <LemonInput
                                    type="number"
                                    size="small"
                                    className="w-20"
                                    value={percentageValue}
                                    onChange={(value) =>
                                        updateConditionSet(index, { rollout_percentage: Number(value) || 0 })
                                    }
                                    min={0.1}
                                    max={100}
                                    step={0.1}
                                    suffix={<span>%</span>}
                                    aria-label="Sampling percentage"
                                    status={percentageValue === 0 ? 'danger' : undefined}
                                />
                                <span>{hasFilters ? `of ${unitPlural} where` : `of all ${unitPlural}`}</span>
                                <PropertyFilters
                                    propertyFilters={condition.properties}
                                    onChange={(properties) => updateConditionSet(index, { properties })}
                                    pageKey={`evaluation-condition-${condition.id}`}
                                    taxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.EventProperties,
                                        TaxonomicFilterGroupType.EventMetadata,
                                        TaxonomicFilterGroupType.PersonProperties,
                                    ]}
                                    buttonSize="small"
                                    hasRowOperator={false}
                                    sendAllKeyUpdates
                                    allowRelativeDateOptions={false}
                                />
                                <LemonMenu
                                    items={[
                                        { label: 'Duplicate', onClick: () => duplicateConditionSet(index) },
                                        {
                                            label: 'Remove',
                                            status: 'danger',
                                            onClick: () => removeConditionSet(index),
                                            disabledReason:
                                                current.length === 1
                                                    ? 'It needs at least one condition set'
                                                    : undefined,
                                        },
                                    ]}
                                >
                                    <LemonButton
                                        icon={<IconEllipsis />}
                                        size="small"
                                        aria-label={`Condition set ${index + 1} actions`}
                                    />
                                </LemonMenu>
                            </div>
                        </div>
                        {percentageValue === 0 && (
                            <span className="text-xs text-danger pl-14">
                                Set a sampling percentage between 0.1% and 100%.
                            </span>
                        )}
                    </div>
                )
            })}
            <div className="pl-12 pt-1">
                <LemonButton type="tertiary" size="small" icon={<IconPlus />} onClick={addConditionSet}>
                    Add condition set
                </LemonButton>
            </div>
        </div>
    )
}
