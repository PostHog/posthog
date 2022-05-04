import './CohortCriteriaRowBuilder.scss'
import React from 'react'
import {BehavioralFilterType, CohortFieldProps, Field, FilterType} from 'scenes/cohorts/CohortFilters/types'
import { renderField, ROWS } from 'scenes/cohorts/CohortFilters/constants'
import { Row, Col, Divider } from 'antd'
import { LemonButton } from 'lib/components/LemonButton'
import { IconCopy, IconDelete } from 'lib/components/icons'
import { AnyCohortCriteriaType, FilterLogicalOperator } from '~/types'
import clsx from "clsx";
import { Field as KeaField } from 'kea-forms'
import {AlertMessage} from "lib/components/AlertMessage";
import {useActions} from "kea";
import {cohortLogic} from "scenes/cohorts/cohortLogic";

export interface CohortCriteriaRowBuilderProps {
    criteria: AnyCohortCriteriaType
    type: BehavioralFilterType
    groupIndex: number
    index: number
    logicalOperator: FilterLogicalOperator
    hideDeleteIcon?: boolean
}

export function CohortCriteriaRowBuilder({
    type,
    groupIndex,
    index,
    logicalOperator,
    criteria,
    hideDeleteIcon = false,
}: CohortCriteriaRowBuilderProps): JSX.Element {
    const {onChangeFilterType, duplicateFilter, removeFilter, setCriteria} = useActions(cohortLogic)
    const rowShape = ROWS[type]
    console.log("TYPE", type, rowShape)

    const renderFieldComponent = (_field: Field, i: number): JSX.Element => {
        return (
            <Col key={i}>
                {renderField[_field.type]({
                    fieldKey: _field.fieldKey,
                    criteria,
                    ...(_field.type === FilterType.Text ? {value: _field.defaultValue} : {}),
                    onChange: (newCriteria) => setCriteria(newCriteria, groupIndex, index),
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
            <KeaField
                name="id"
                template={({error, kids}) => {
                    return (
                        <>
                            <div
                                className={clsx('CohortCriteriaRow__Criteria', error && `CohortCriteriaRow__Criteria--error`)}>
                                {kids}
                                {error && (
                                <Row
                                    className='CohortCriteriaRow__Criteria__error-row'>
                                    <AlertMessage type='error' style={{width: "100%"}}>
                                        <>
                                            {error}
                                        </>
                                    </AlertMessage>
                                </Row>
                            )}
                            </div>
                        </>
                    )
                }}
            >
                <>
                    <Row align="middle" wrap={false} className="mb-025">
                        <KeaField
                            name='value'
                            template={({error, kids}) => {
                                return (
                                    <>
                                        <div
                                            className={clsx('CohortCriteriaRow__Criteria__Field', error && `CohortCriteriaRow__Criteria__Field--error`)}>
                                            {kids}
                                        </div>
                                    </>
                                )
                            }}
                        >
                            <>
                                <Col>
                                    {renderField[FilterType.Behavioral]({
                                        fieldKey: 'value',
                                        criteria,
                                        onChange: (newCriteria) => onChangeFilterType(newCriteria, groupIndex, index),
                                    })}
                                </Col>
                            </>
                        </KeaField>
                        <div className="CohortCriteriaRow__inline-divider"/>
                        <LemonButton icon={<IconCopy/>} type="primary-alt"
                                     onClick={() => duplicateFilter(groupIndex, index)} compact/>
                        {!hideDeleteIcon && (
                            <LemonButton icon={<IconDelete/>} type="primary-alt"
                                         onClick={() => removeFilter(groupIndex, index)} compact/>
                        )}
                    </Row>
                    <div style={{display: 'flex'}}>
                        <Col>
                            <span className="CohortCriteriaRow__Criteria__arrow">&#8627;</span>
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
                                                                <div
                                                                    className={clsx('CohortCriteriaRow__Criteria__Field', error && `CohortCriteriaRow__Criteria__Field--error`)}>
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
                                                <div className="CohortCriteriaRow__Criteria__Field">
                                                    {renderFieldComponent(field, i)}
                                                </div>
                                            )
                                        )
                                    )
                                })}
                            </Row>
                        </div>
                    </div>
                </>
            </KeaField>
        </div>
    )
}
