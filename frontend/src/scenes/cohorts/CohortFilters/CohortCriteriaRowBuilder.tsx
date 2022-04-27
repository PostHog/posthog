import './CohortCriteriaRowBuilder.scss'
import React from 'react'
import { BehavioralFilterType, CohortFieldProps, FilterType } from 'scenes/cohorts/CohortFilters/types'
import { renderField, ROWS } from 'scenes/cohorts/CohortFilters/constants'
import { Row, Col } from 'antd'

export interface CohortCriteriaRowBuilderProps {
    /* Object that contains keys and values corresponding to filter row.
    TODO: stronger schema typing once API is finalized*/
    groupedValues?: Record<string, any>[]
    type: BehavioralFilterType
    onChangeType: (type: BehavioralFilterType) => void
}

export function CohortCriteriaRowBuilder({
    type,
    groupedValues,
    onChangeType,
}: CohortCriteriaRowBuilderProps): JSX.Element {
    const rowShape = ROWS[type]
    return (
        <Row className="CohortCriteriaRow" align="middle">
            <Col className="CohortCriteriaRow__CohortField">
                {renderField[FilterType.Behavioral]({
                    value: type,
                    groupedValues,
                    onChange: (val) => onChangeType(val as BehavioralFilterType),
                })}
            </Col>
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
    )
}
