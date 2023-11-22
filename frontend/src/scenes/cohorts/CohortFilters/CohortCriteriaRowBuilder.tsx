import './CohortCriteriaRowBuilder.scss'

import { Divider } from 'antd'
import clsx from 'clsx'
import { useActions } from 'kea'
import { Field as KeaField } from 'kea-forms'
import { IconCopy, IconDelete } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cohortEditLogic, CohortLogicProps } from 'scenes/cohorts/cohortEditLogic'
import { renderField, ROWS } from 'scenes/cohorts/CohortFilters/constants'
import { BehavioralFilterType, CohortFieldProps, Field, FilterType } from 'scenes/cohorts/CohortFilters/types'
import { cleanCriteria } from 'scenes/cohorts/cohortUtils'

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
    id,
    type,
    groupIndex,
    index,
    logicalOperator,
    criteria,
    hideDeleteIcon = false,
    onChangeType,
}: CohortCriteriaRowBuilderProps): JSX.Element {
    const { setCriteria, duplicateFilter, removeFilter } = useActions(cohortEditLogic({ id }))
    const rowShape = ROWS[type]

    const renderFieldComponent = (_field: Field, i: number): JSX.Element => {
        return (
            <div key={_field.fieldKey ?? i}>
                {renderField[_field.type]({
                    fieldKey: _field.fieldKey,
                    criteria,
                    ...(_field.type === FilterType.Text ? { value: _field.defaultValue } : {}),
                    ...(_field.groupTypeFieldKey ? { groupTypeFieldKey: _field.groupTypeFieldKey } : {}),
                    onChange: (newCriteria) => setCriteria(newCriteria, groupIndex, index),
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
                                {kids}
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
                                            {kids}
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
                                        onChange: (newCriteria) => {
                                            setCriteria(cleanCriteria(newCriteria, true), groupIndex, index)
                                            onChangeType?.(newCriteria['value'] ?? BehavioralEventType.PerformEvent)
                                        },
                                    })}
                                </div>
                            </>
                        </KeaField>
                        <div className="CohortCriteriaRow__inline-divider" />
                        <LemonButton
                            icon={<IconCopy />}
                            status="primary-alt"
                            onClick={() => duplicateFilter(groupIndex, index)}
                        />
                        {!hideDeleteIcon && (
                            <LemonButton
                                icon={<IconDelete />}
                                status="primary-alt"
                                onClick={() => removeFilter(groupIndex, index)}
                            />
                        )}
                    </div>
                    <div className="flex">
                        <div>
                            <span className="CohortCriteriaRow__Criteria__arrow">&#8627;</span>
                        </div>
                        <div>
                            <div className="flex items-center">
                                {rowShape.fields.map((field, i) => {
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
                                                                {kids}
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
                    </div>
                </>
            </KeaField>
        </div>
    )
}

export interface LogicalRowDividerProps {
    logicalOperator: FilterLogicalOperator
}

export function LogicalRowDivider({ logicalOperator }: LogicalRowDividerProps): JSX.Element {
    return (
        <Divider className="logical-row-divider" orientation="left">
            <span className="text-xs text-primary-alt font-semibold">{logicalOperator}</span>
        </Divider>
    )
}
