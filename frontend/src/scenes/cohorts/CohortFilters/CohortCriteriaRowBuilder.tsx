import './CohortCriteriaRowBuilder.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Field as KeaField } from 'kea-forms'

import { IconCopy, IconTrash } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { eventsWithMoveNotice } from 'lib/components/TaxonomicFilter/utils/hiddenEvents'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CohortLogicProps, cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { getRowShape, renderField } from 'scenes/cohorts/CohortFilters/constants'
import { BehavioralFilterType, CohortFieldProps, Field, FilterType } from 'scenes/cohorts/CohortFilters/types'
import { cleanCriteria } from 'scenes/cohorts/cohortUtils'
import { teamLogic } from 'scenes/teamLogic'

import { AnyCohortCriteriaType, BehavioralEventType, FilterLogicalOperator } from '~/types'

export interface CohortCriteriaRowBuilderProps {
    id: CohortLogicProps['id']
    criteria: AnyCohortCriteriaType
    type: BehavioralFilterType
    groupIndex: number
    index: number
    logicalOperator: FilterLogicalOperator
    hideDeleteIcon?: boolean
    onChangeType?: (nextType: BehavioralFilterType) => void
}

export function CohortCriteriaRowBuilder({
    type,
    groupIndex,
    index,
    logicalOperator,
    criteria,
    hideDeleteIcon = false,
    onChangeType,
}: CohortCriteriaRowBuilderProps): JSX.Element {
    const { setCriteria, duplicateFilter, removeFilter } = useActions(cohortEditLogic)
    const { currentTeam } = useValues(teamLogic)
    const moveNoticeEvents = eventsWithMoveNotice(
        currentTeam?.flag_evaluations_mode,
        useFeatureFlag('FLAG_CALLED_MOVE_NOTICES')
    )
    const showsMoveNotice =
        (criteria.event_type === TaxonomicFilterGroupType.Events && moveNoticeEvents.includes(String(criteria.key))) ||
        (criteria.seq_event_type === TaxonomicFilterGroupType.Events &&
            moveNoticeEvents.includes(String(criteria.seq_event)))
    // Falling back to another row's fields would let an edit merge into the unmapped criterion,
    // which cleanCriteria then strips to undefined. An empty row keeps the type selector as the
    // recovery path.
    const rowShape = getRowShape(type)
    const rowFields = rowShape?.fields ?? []

    const renderFieldComponent = (_field: Field, i: number): JSX.Element => {
        return (
            <div key={_field.fieldKey ?? i}>
                {renderField[_field.type]({
                    fieldKey: _field.fieldKey,
                    criteria,
                    ...(_field.type === FilterType.Text ? { value: _field.defaultValue } : {}),
                    ...(_field.groupTypeFieldKey ? { groupTypeFieldKey: _field.groupTypeFieldKey } : {}),
                    onChange: (newCriteria) => setCriteria(newCriteria, groupIndex, index),
                    groupIndex,
                    index,
                } as CohortFieldProps)}
            </div>
        )
    }

    return (
        <div className="CohortCriteriaRow">
            {index !== 0 && <LogicalRowDivider logicalOperator={logicalOperator} />}
            <KeaField
                name="id"
                template={({ error, kids }) => {
                    return (
                        <>
                            <div
                                className={clsx(
                                    'CohortCriteriaRow__Criteria',
                                    error && `CohortCriteriaRow__Criteria--error`
                                )}
                            >
                                {kids as React.ReactNode}
                                {error && (
                                    <LemonBanner className="my-2" type="error">
                                        {error}
                                    </LemonBanner>
                                )}
                            </div>
                        </>
                    )
                }}
            >
                <>
                    <div className="flex flex-nowrap items-center mb-1">
                        <KeaField
                            name="value"
                            template={({ error, kids }) => {
                                return (
                                    <>
                                        <div
                                            className={clsx(
                                                'CohortCriteriaRow__Criteria__Field',
                                                error && `CohortCriteriaRow__Criteria__Field--error`
                                            )}
                                        >
                                            {kids as React.ReactNode}
                                        </div>
                                    </>
                                )
                            }}
                        >
                            <>
                                <div>
                                    {renderField[FilterType.Behavioral]({
                                        fieldKey: 'value',
                                        criteria,
                                        placeholder: 'Choose criterion',
                                        onChange: (newCriteria) => {
                                            setCriteria(cleanCriteria(newCriteria, true), groupIndex, index)
                                            onChangeType?.(newCriteria['value'] ?? BehavioralEventType.PerformEvent)
                                        },
                                    })}
                                </div>
                            </>
                        </KeaField>
                        <div className="CohortCriteriaRow__inline-divider" />
                        <LemonButton icon={<IconCopy />} onClick={() => duplicateFilter(groupIndex, index)} />
                        {!hideDeleteIcon && (
                            <LemonButton icon={<IconTrash />} onClick={() => removeFilter(groupIndex, index)} />
                        )}
                    </div>
                    {!rowShape && (
                        <LemonBanner className="my-2" type="warning">
                            This criterion isn't valid. Choose a new one to replace it.
                        </LemonBanner>
                    )}
                    {/* The arrow points at the fields, so it has nothing to point at on an empty row. */}
                    {rowFields.length > 0 && (
                        <div className="flex">
                            <span className="CohortCriteriaRow__Criteria__arrow">&#8627;</span>
                            <div className="flex flex-wrap items-center min-w-0">
                                {rowFields.map((field, i) => {
                                    return (
                                        !field.hide &&
                                        (field.fieldKey ? (
                                            <KeaField
                                                key={i}
                                                name={field.fieldKey}
                                                template={({ error, kids }) => {
                                                    return (
                                                        <>
                                                            <div
                                                                className={clsx(
                                                                    'CohortCriteriaRow__Criteria__Field',
                                                                    error && `CohortCriteriaRow__Criteria__Field--error`
                                                                )}
                                                            >
                                                                {kids as React.ReactNode}
                                                            </div>
                                                        </>
                                                    )
                                                }}
                                            >
                                                <>{renderFieldComponent(field, i)}</>
                                            </KeaField>
                                        ) : (
                                            <div key={i} className="CohortCriteriaRow__Criteria__Field">
                                                {renderFieldComponent(field, i)}
                                            </div>
                                        ))
                                    )
                                })}
                            </div>
                        </div>
                    )}
                    {showsMoveNotice && (
                        <LemonBanner className="my-2" type="warning">
                            Feature flag called is moving out of the events table. Once your organization starts the
                            move, you can't add new criteria on it. When the move finishes, this criterion stops
                            matching new flag calls. To see how a flag is used, open the flag and check its Usage tab.
                        </LemonBanner>
                    )}
                </>
            </KeaField>
        </div>
    )
}

export interface LogicalRowDividerProps {
    logicalOperator: FilterLogicalOperator
}

export function LogicalRowDivider({ logicalOperator }: LogicalRowDividerProps): JSX.Element {
    return <LemonDivider className="logical-row-divider my-4" label={logicalOperator} />
}
