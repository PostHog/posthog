import './CohortCriteriaRowBuilder.scss'
import React from 'react'
import { BehavioralFilterType, CohortFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'
import { renderField, ROWS } from 'scenes/cohorts/CohortFilters/constants'
import { Row, Col, Divider } from 'antd'
import { LemonButton } from 'lib/components/LemonButton'
import { IconCopy, IconDelete } from 'lib/components/icons'
import { AnyCohortCriteriaType, FilterLogicalOperator } from '~/types'
import { behavioralFilterTypeToCriteria } from 'scenes/cohorts/cohortUtils'

export interface CohortCriteriaRowBuilderProps {
    criteria: AnyCohortCriteriaType
    type: BehavioralFilterType
    groupIndex: number
    index: number
    logicalOperator: FilterLogicalOperator
    onDuplicate?: () => void
    onRemove?: () => void
    onChange?: (newCriteria: AnyCohortCriteriaType, groupIndex: number, criteriaIndex: number) => void
}

export function CohortCriteriaRowBuilder({
    type,
    groupIndex,
    index,
    logicalOperator,
    criteria,
    onChange,
    onDuplicate,
    onRemove,
}: CohortCriteriaRowBuilderProps): JSX.Element {
    const rowShape = ROWS[type]

    const onChangeType = (newCriteria: AnyCohortCriteriaType): void => {
        // Populate empty values with default values on changing type
        const populatedCriteria = {}

        const { fields, ...apiProps } = newCriteria?.value ? ROWS[newCriteria.value] : rowShape
        Object.entries(apiProps).forEach(([key, defaultValue]) => {
            const nextValue = newCriteria[key] ?? defaultValue
            if (nextValue) {
                populatedCriteria[key] = nextValue
            }
        })
        fields.forEach(({ fieldKey, defaultValue }) => {
            const nextValue = fieldKey ? newCriteria[fieldKey] ?? defaultValue : null
            if (fieldKey && nextValue) {
                populatedCriteria[fieldKey] = nextValue
            }
        })
        console.log('POPULATED CRITERIA', newCriteria, populatedCriteria)
        onChange?.(
            { ...populatedCriteria, ...behavioralFilterTypeToCriteria(populatedCriteria['value']) },
            groupIndex,
            index
        )
    }

    return (
        <div className="CohortCriteriaRow">
            {index !== 0 && (
                <Divider className="CohortCriteriaRow__logical-divider" orientation="left">
                    {logicalOperator}
                </Divider>
            )}
            <Row align="middle" wrap={false} className="mb-025">
                <Col>
                    {renderField[FilterType.Behavioral]({
                        fieldKey: 'value',
                        criteria,
                        onChange: (newCriteria) => onChangeType(newCriteria),
                    })}
                </Col>
                <div className="CohortCriteriaRow__inline-divider" />
                <LemonButton icon={<IconCopy />} type="primary-alt" onClick={() => onDuplicate?.()} compact />
                <LemonButton icon={<IconDelete />} type="primary-alt" onClick={() => onRemove?.()} compact />
            </Row>
            <div style={{ display: 'flex' }}>
                <Col>
                    <span className="CohortCriteriaRow__arrow">&#8627;</span>
                </Col>
                <div>
                    <Row align="middle">
                        {rowShape.fields.map((field, i) => {
                            return (
                                !field.hide && (
                                    <Col key={i} className="CohortCriteriaRow__CohortField">
                                        {renderField[field.type]({
                                            fieldKey: field.fieldKey,
                                            criteria,
                                            ...(field.type === FilterType.Text ? { value: field.defaultValue } : {}),
                                            onChange: (newCriteria) => onChange?.(newCriteria, groupIndex, index),
                                        } as CohortFieldProps)}
                                    </Col>
                                )
                            )
                        })}
                    </Row>
                </div>
            </div>
        </div>
    )
}
