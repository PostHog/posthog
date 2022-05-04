import './CohortCriteriaRowBuilder.scss'
import React from 'react'
import {BehavioralFilterType, CohortFieldProps, Field, FilterType} from 'scenes/cohorts/CohortFilters/types'
import { renderField, ROWS } from 'scenes/cohorts/CohortFilters/constants'
import { Row, Col, Divider } from 'antd'
import { LemonButton } from 'lib/components/LemonButton'
import { IconCopy, IconDelete } from 'lib/components/icons'
import { AnyCohortCriteriaType, FilterLogicalOperator } from '~/types'
import {criteriaToBehavioralFilterType, determineFilterType} from 'scenes/cohorts/cohortUtils'
import clsx from "clsx";
import { Field as KeaField } from 'kea-forms'
import {AlertMessage} from "lib/components/AlertMessage";

export interface CohortCriteriaRowBuilderProps {
    criteria: AnyCohortCriteriaType
    type: BehavioralFilterType
    groupIndex: number
    index: number
    logicalOperator: FilterLogicalOperator
    onDuplicate?: () => void
    onRemove?: () => void
    onChange?: (newCriteria: AnyCohortCriteriaType, groupIndex: number, criteriaIndex: number) => void
    hideDeleteIcon?: boolean
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
    hideDeleteIcon = false,
}: CohortCriteriaRowBuilderProps): JSX.Element {
    const rowShape = ROWS[type]

    const onChangeType = (newCriteria: AnyCohortCriteriaType): void => {
        // Populate empty values with default values on changing type
        const populatedCriteria = {}

        const { fields, ...apiProps } = ROWS[criteriaToBehavioralFilterType(newCriteria)] ?? rowShape
        Object.entries(apiProps).forEach(([key, defaultValue]) => {
            const nextValue = newCriteria[key] ?? defaultValue
            if (nextValue !== undefined && nextValue !== null) {
                populatedCriteria[key] = nextValue
            }
        })
        fields.forEach(({ fieldKey, defaultValue }) => {
            const nextValue = fieldKey ? newCriteria[fieldKey] ?? defaultValue : null
            if (fieldKey && nextValue !== undefined && nextValue !== null) {
                populatedCriteria[fieldKey] = nextValue
            }
        })
        console.log("ONCHANGETYPE", {
                ...populatedCriteria,
                ...determineFilterType(
                    populatedCriteria['type'],
                    populatedCriteria['value'],
                    populatedCriteria['negation']
                ),
            })
        onChange?.(
            {
                ...populatedCriteria,
                ...determineFilterType(
                    populatedCriteria['type'],
                    populatedCriteria['value'],
                    populatedCriteria['negation']
                ),
            },
            groupIndex,
            index
        )
    }

    const renderFieldComponent = (_field: Field, i: number): JSX.Element => {
        return (
            <Col key={i}>
                {renderField[_field.type]({
                    fieldKey: _field.fieldKey,
                    criteria,
                    ...(_field.type === FilterType.Text ? {value: _field.defaultValue} : {}),
                    onChange: (newCriteria) => onChange?.(newCriteria, groupIndex, index),
                } as CohortFieldProps)}
            </Col>
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
                {!hideDeleteIcon && (
                    <LemonButton icon={<IconDelete />} type="primary-alt" onClick={() => onRemove?.()} compact />
                )}
            </Row>
            <div style={{ display: 'flex' }}>
                <Col>
                    <span className="CohortCriteriaRow__arrow">&#8627;</span>
                </Col>
                <div>
                    <Row align="middle">
                        {rowShape.fields.map((field, i) => {
                            return (
                                !field.hide && (field.fieldKey ? (
                                        <KeaField
                                            name={field.fieldKey}
                                            template={({error, kids}) => {
                                                return (
                                                    <>
                                                        {error && (
                                                            <Row
                                                                className='CohortCriteriaRow__CohortField__error-row'>
                                                                <AlertMessage type='error' style={{width: "100%"}}>
                                                                    <>
                                                                        {error}
                                                                    </>
                                                                </AlertMessage>
                                                            </Row>
                                                        )}
                                                        <div
                                                            className={clsx('CohortCriteriaRow__CohortField', error && `CohortCriteriaRow__CohortField--error`)}>
                                                            {kids}
                                                        </div>
                                                    </>
                                                )
                                            }}
                                        >
                                            <>
                                                {renderFieldComponent(field, i)}
                                            </>
                                        </KeaField>
                                    ) : (
                                        <div className="CohortCriteriaRow__CohortField">
                                            {renderFieldComponent(field, i)}
                                        </div>
                                    )
                                )
                            )
                        })}
                    </Row>
                </div>
            </div>
        </div>
    )
}
