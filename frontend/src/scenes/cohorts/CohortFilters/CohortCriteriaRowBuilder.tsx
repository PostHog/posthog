import './CohortCriteriaRowBuilder.scss'
import React from 'react'
import { BehavioralFilterType, CohortFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'
import { renderField, ROWS } from 'scenes/cohorts/CohortFilters/constants'
import { Row, Col } from 'antd'
import { LemonButton } from 'lib/components/LemonButton'
import { IconCopy, IconDelete } from 'lib/components/icons'
import { AnyCohortCriteriaType } from '~/types'

export interface CohortCriteriaRowBuilderProps {
    /* Object that contains keys and values corresponding to filter row.
    TODO: stronger schema typing once API is finalized*/
    groupedValues?: AnyCohortCriteriaType[]
    type: BehavioralFilterType
    onChangeType: (type: BehavioralFilterType) => void
    onDuplicate?: () => void
    onRemove?: () => void
}

export function CohortCriteriaRowBuilder({
    type,
    groupedValues,
    onChangeType,
    onDuplicate,
    onRemove,
}: CohortCriteriaRowBuilderProps): JSX.Element {
    const rowShape = ROWS[type]
    return (
        <div className="CohortCriteriaRow">
            <Row align="middle" wrap={false} className="mb-025">
                <Col>
                    {renderField[FilterType.Behavioral]({
                        value: type,
                        groupedValues,
                        onChange: (val) => onChangeType(val as BehavioralFilterType),
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
                        {rowShape.fields.map(
                            (field, i) =>
                                !field.hide && (
                                    <Col key={i} className="CohortCriteriaRow__CohortField">
                                        {renderField[field.type]({
                                            value: null,
                                            ...field,
                                            ...(groupedValues?.[i] ?? {}),
                                            groupedValues,
                                        } as CohortFieldProps)}
                                    </Col>
                                )
                        )}
                    </Row>
                </div>
            </div>
        </div>
    )
}
