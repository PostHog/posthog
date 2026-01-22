import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { allOperatorsToHumanName } from 'lib/components/DefinitionPopover/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { AnyPropertyFilter, FeatureFlagGroupType, PropertyFilterType } from '~/types'

import {
    FeatureFlagReleaseConditionsLogicProps,
    featureFlagReleaseConditionsLogic,
} from './featureFlagReleaseConditionsLogic'

interface FeatureFlagReleaseConditionsCollapsibleProps extends FeatureFlagReleaseConditionsLogicProps {
    readOnly?: boolean
}

function summarizeProperties(properties: AnyPropertyFilter[]): string {
    if (!properties || properties.length === 0) {
        return 'All users'
    }

    const parts = properties.slice(0, 2).map((property) => {
        const key = property.type === PropertyFilterType.Cohort ? 'Cohort' : property.key || 'property'
        const operator = isPropertyFilterWithOperator(property) ? allOperatorsToHumanName(property.operator) : 'is'
        const value = Array.isArray(property.value)
            ? property.value.slice(0, 2).join(', ') + (property.value.length > 2 ? '...' : '')
            : property.value

        return `${key} ${operator} ${value}`
    })

    if (properties.length > 2) {
        parts.push(`+${properties.length - 2} more`)
    }

    return parts.join(' AND ')
}

function ConditionSummary({ group, index }: { group: FeatureFlagGroupType; index: number }): JSX.Element {
    const summary = summarizeProperties(group.properties || [])
    const rollout = group.rollout_percentage ?? 100

    return (
        <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-2">
                <span className="font-medium text-xs bg-bg-light rounded px-1.5 py-0.5">{index + 1}</span>
                <span className="text-sm truncate max-w-[300px]" title={summary}>
                    {summary}
                </span>
            </div>
            <span className="text-sm text-muted ml-2">({rollout}%)</span>
        </div>
    )
}

export function FeatureFlagReleaseConditionsCollapsible({
    id,
    filters,
    onChange,
    readOnly,
}: FeatureFlagReleaseConditionsCollapsibleProps): JSX.Element {
    const releaseConditionsLogic = featureFlagReleaseConditionsLogic({
        id,
        readOnly,
        filters,
        onChange,
    })

    const { taxonomicGroupTypes, filterGroups, filtersTaxonomicOptions } = useValues(releaseConditionsLogic)
    const { updateConditionSet, removeConditionSet, addConditionSet } = useActions(releaseConditionsLogic)

    const [openConditions, setOpenConditions] = useState<string[]>(filterGroups.length === 1 ? ['condition-0'] : [])

    if (readOnly) {
        return (
            <div className="flex flex-col gap-2">
                <LemonLabel>Release conditions</LemonLabel>
                {filterGroups.map((group, index) => (
                    <div key={group.sort_key} className="flex flex-col gap-1">
                        {index > 0 && <div className="text-xs text-muted text-center">OR</div>}
                        <div className="rounded border p-3 bg-bg-light">
                            <div className="text-sm">
                                <ConditionSummary group={group} index={index} />
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <LemonLabel>Release conditions</LemonLabel>
            </div>
            <p className="text-xs text-muted mb-2">
                Specify users for flag release. Condition sets are evaluated top to bottom - the first matching set is
                used. A condition matches when all property filters pass AND the target falls within the rollout
                percentage.
            </p>

            <LemonCollapse
                multiple
                activeKeys={openConditions}
                onChange={setOpenConditions}
                panels={filterGroups.map((group, index) => ({
                    key: `condition-${index}`,
                    header: <ConditionSummary group={group} index={index} />,
                    className: index > 0 ? 'mt-1' : '',
                    content: (
                        <div className="flex flex-col gap-3 pt-2">
                            <div>
                                <div className="flex items-center justify-between mb-1">
                                    <LemonLabel>Match filters</LemonLabel>
                                    {(!group.properties || group.properties.length === 0) && (
                                        <span className="text-muted text-xs">Matches all users</span>
                                    )}
                                </div>
                                <PropertyFilters
                                    orFiltering={true}
                                    pageKey={`feature-flag-workflow-${id}-${index}`}
                                    propertyFilters={group?.properties}
                                    logicalRowDivider
                                    addText="Add filter"
                                    onChange={(properties) => updateConditionSet(index, undefined, properties)}
                                    taxonomicGroupTypes={taxonomicGroupTypes}
                                    taxonomicFilterOptionsFromProp={filtersTaxonomicOptions}
                                    hasRowOperator={false}
                                />
                            </div>

                            <div>
                                <LemonLabel className="mb-1">Rollout percentage</LemonLabel>
                                <div className="flex items-center gap-3">
                                    <div className="flex-1">
                                        <LemonSlider
                                            value={group.rollout_percentage ?? 100}
                                            onChange={(value) => updateConditionSet(index, value)}
                                            min={0}
                                            max={100}
                                            step={1}
                                        />
                                    </div>
                                    <LemonInput
                                        type="number"
                                        min={0}
                                        max={100}
                                        value={group.rollout_percentage ?? 100}
                                        onChange={(value) => {
                                            const numValue = value ? parseInt(value.toString()) : 0
                                            updateConditionSet(index, Math.min(100, Math.max(0, numValue)))
                                        }}
                                        suffix={<span>%</span>}
                                        className="w-20"
                                    />
                                </div>
                            </div>

                            {filterGroups.length > 1 && (
                                <div className="flex justify-end">
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        size="small"
                                        icon={<IconTrash />}
                                        onClick={() => removeConditionSet(index)}
                                    >
                                        Remove condition
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    ),
                }))}
            />

            {filterGroups.length > 1 &&
                filterGroups.map((_, index) =>
                    index > 0 ? (
                        <div
                            key={`or-${index}`}
                            className="text-xs text-muted text-center -my-1"
                            style={{ order: index * 2 - 1 }}
                        >
                            OR
                        </div>
                    ) : null
                )}

            <LemonButton type="secondary" icon={<IconPlus />} onClick={addConditionSet} className="mt-1">
                Add condition set
            </LemonButton>
        </div>
    )
}
