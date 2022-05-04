import './Cohort.scss'
import React from 'react'
import { useActions, useValues } from 'kea'
import { Field as KeaField, Group } from 'kea-forms'
import { Col, Divider, Row } from 'antd'
import { AvailableFeature, CohortGroupType, CohortType } from '~/types'
import { CohortTypeEnum, PROPERTY_MATCH_TYPE } from 'lib/constants'
import { PlusOutlined } from '@ant-design/icons'
import Dragger from 'antd/lib/upload/Dragger'
import { Persons } from 'scenes/persons/Persons'
import { cohortLogic } from './cohortLogic'
import { userLogic } from 'scenes/userLogic'
import 'antd/lib/dropdown/style/index.css'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonButton } from 'lib/components/LemonButton'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { Field } from 'lib/forms/Field'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { LemonSelect } from 'lib/components/LemonSelect'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { IconCopy, IconDelete, IconPlusMini, IconUploadFile } from 'lib/components/icons'
import { UploadFile } from 'antd/es/upload/interface'
import { MatchCriteriaSelector } from 'scenes/cohorts/MatchCriteriaSelector'
import { Tooltip } from 'lib/components/Tooltip'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { AndOrFilterSelect } from 'lib/components/PropertyGroupFilters/PropertyGroupFilters'
import { alphabet } from 'lib/utils'
import { Lettermark, LettermarkColor } from 'lib/components/Lettermark/Lettermark'
import { LemonDivider } from 'lib/components/LemonDivider'
import { CohortCriteriaRowBuilder } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'
import { criteriaToBehavioralFilterType, isCohortCriteriaGroup } from 'scenes/cohorts/cohortUtils'
import { COHORT_TYPE_OPTIONS } from 'scenes/cohorts/CohortFilters/constants'
import clsx from "clsx";
import {AlertMessage} from "lib/components/AlertMessage";

export const scene: SceneExport = {
    component: Cohort,
    paramsToProps: ({ params: { id } }) => ({ id: id && id !== 'new' ? parseInt(id) : 'new' }),
}

export function Cohort({ id }: { id?: CohortType['id'] } = {}): JSX.Element {
    const logicProps = { id }
    const logic = cohortLogic(logicProps)
    const {
        deleteCohort,
        setCohort,
        onCriteriaChange,
        setOuterGroupsType,
        setInnerGroupType,
        duplicateFilter,
        removeFilter,
        addFilter,
        setCriteria,
    } = useActions(logic)
    const { cohort, cohortLoading, newCohortFiltersEnabled, cohortErrors } = useValues(logic)
    const { hasAvailableFeature } = useValues(userLogic)
    const isNewCohort = cohort.id === 'new' || cohort.id === undefined

    console.log('COHORT', cohort, cohortErrors)

    return (
        <div className="cohort">
            <VerticalForm logic={cohortLogic} props={logicProps} formKey="cohort">
                <PageHeader
                    title={isNewCohort ? 'New cohort' : cohort.name || 'Untitled'}
                    buttons={
                        <div className="flex-center">
                            {isNewCohort ? (
                                <LemonButton
                                    data-attr="cancel-cohort"
                                    type="secondary"
                                    onClick={() => {
                                        router.actions.push(urls.cohorts())
                                    }}
                                    style={{ marginRight: 8 }}
                                    disabled={cohortLoading}
                                >
                                    Cancel
                                </LemonButton>
                            ) : (
                                <LemonButton
                                    data-attr="delete-cohort"
                                    status="danger"
                                    type="secondary"
                                    onClick={() => {
                                        deleteCohort()
                                    }}
                                    style={{ marginRight: 8 }}
                                    disabled={cohortLoading}
                                >
                                    Delete
                                </LemonButton>
                            )}
                            <LemonButton
                                type="primary"
                                data-attr="save-cohort"
                                htmlType="submit"
                                loading={cohortLoading}
                            >
                                Save
                            </LemonButton>
                        </div>
                    }
                />
                <Divider />
                <Row gutter={[16, 24]} style={{ maxWidth: 640 }}>
                    <Col xs={24} sm={12}>
                        <Field name="name" label="Name">
                            {({ value, onValueChange }) => (
                                <LemonInput value={value} onChange={onValueChange} data-attr="cohort-name" />
                            )}
                        </Field>
                    </Col>
                    <Col xs={24} sm={12}>
                        <Field name="is_static" label="Type">
                            {({ value, onValueChange }) => (
                                <Tooltip
                                    title={
                                        isNewCohort ? null : 'Create a new cohort to use a different type of cohort.'
                                    }
                                >
                                    <div>
                                        <LemonSelect
                                            disabled={!isNewCohort}
                                            options={COHORT_TYPE_OPTIONS}
                                            value={value ? CohortTypeEnum.Static : CohortTypeEnum.Dynamic}
                                            onChange={(cohortType) => {
                                                onValueChange(cohortType === CohortTypeEnum.Static)
                                            }}
                                            type="stealth"
                                            outlined
                                            style={{ width: '100%' }}
                                            data-attr="cohort-type"
                                        />
                                    </div>
                                </Tooltip>
                            )}
                        </Field>
                    </Col>
                </Row>
                {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && (
                    <Row gutter={[16, 24]} className="mt ph-ignore-input" style={{ maxWidth: 640 }}>
                        <Col span={24}>
                            <Field name="description" label="Description" data-attr="cohort-description">
                                {({ value, onValueChange }) => <LemonTextArea value={value} onChange={onValueChange} />}
                            </Field>
                        </Col>
                    </Row>
                )}
                {cohort.is_static ? (
                    <Row gutter={24} className="mt ph-ignore-input">
                        <Col span={24}>
                            <Field name="csv" label={isNewCohort ? 'Upload users' : 'Add users'} data-attr="cohort-csv">
                                {({ onValueChange }) => (
                                    <>
                                        <span className="mb">
                                            Upload a CSV file to add users to your cohort. The CSV file only requires a
                                            single column with the user’s distinct ID.
                                        </span>
                                        <Dragger
                                            name="file"
                                            multiple={false}
                                            fileList={cohort.csv ? [cohort.csv] : []}
                                            accept=".csv"
                                            showUploadList={false}
                                            beforeUpload={(file: UploadFile) => {
                                                onValueChange(file)
                                                return false
                                            }}
                                            className="cohort-csv-dragger"
                                        >
                                            {cohort.csv ? (
                                                <>
                                                    <IconUploadFile
                                                        style={{ fontSize: '3rem', color: 'var(--muted-alt)' }}
                                                    />
                                                    <div className="ant-upload-text">
                                                        {cohort.csv?.name ?? 'File chosen'}
                                                    </div>
                                                </>
                                            ) : (
                                                <>
                                                    <IconUploadFile
                                                        style={{ fontSize: '3rem', color: 'var(--muted-alt)' }}
                                                    />
                                                    <div className="ant-upload-text">
                                                        Drag a file here or click to browse for a file
                                                    </div>
                                                </>
                                            )}
                                        </Dragger>
                                    </>
                                )}
                            </Field>
                        </Col>
                    </Row>
                ) : (
                    <>
                        <Divider />
                        <Row gutter={24} className="mt">
                            <Col span={24}>
                                <>
                                    <Row align="middle" justify="space-between" wrap={false}>
                                        <Row className="ant-form-item ant-form-item-label" style={{ marginBottom: 0 }}>
                                            <label htmlFor="groups" title="Matching criteria">
                                                Matching criteria
                                            </label>
                                            <span>
                                                Actors who match the following criteria will be part of the cohort.
                                                Continuously updated automatically.
                                            </span>
                                        </Row>
                                        {newCohortFiltersEnabled && (
                                            <Row align="middle" wrap={false} justify="space-between" className="pl">
                                                <AndOrFilterSelect
                                                    value={cohort.filters.properties.type}
                                                    onChange={(value) => {
                                                        setOuterGroupsType(value)
                                                    }}
                                                    topLevelFilter={true}
                                                    suffix="criteria"
                                                />
                                            </Row>
                                        )}
                                    </Row>
                                    {newCohortFiltersEnabled ? (
                                        <>
                                            {cohort.filters.properties.values.map((group, groupIndex) =>
                                                isCohortCriteriaGroup(group) ? (
                                                    <Group
                                                        key={groupIndex}
                                                        name={['filters', 'properties', 'values', groupIndex]}
                                                    >
                                                        {groupIndex !== 0 && (
                                                            <div
                                                                className="cohort-detail__matching-group__logical-divider">
                                                                {cohort.filters.properties.values[groupIndex].type}
                                                            </div>
                                                        )}
                                                        <KeaField
                                                            name="id"
                                                            template={({error, kids}) => {
                                                                return (
                                                                    <div
                                                                        className={clsx('cohort-detail__matching-group', error && `cohort-detail__matching-group--error`)}>
                                                                        <Row align="middle" wrap={false}
                                                                             className="pl pr">
                                                                            <Lettermark
                                                                                name={alphabet[groupIndex]}
                                                                                color={LettermarkColor.Gray}
                                                                            />
                                                                            <AndOrFilterSelect
                                                                                prefix="Match persons against"
                                                                                suffix="criteria"
                                                                                onChange={(value) =>
                                                                                    setInnerGroupType(value, groupIndex)
                                                                                }
                                                                                value={group.type}
                                                                            />
                                                                            <div style={{flex: 1, minWidth: '0.5rem'}}/>
                                                                            <LemonButton
                                                                                icon={<IconCopy/>}
                                                                                type="primary-alt"
                                                                                onClick={() => duplicateFilter(groupIndex)}
                                                                                compact
                                                                            />
                                                                            {cohort.filters.properties.values.length > 1 && (
                                                                                <LemonButton
                                                                                    icon={<IconDelete/>}
                                                                                    type="primary-alt"
                                                                                    onClick={() => removeFilter(groupIndex)}
                                                                                    compact
                                                                                />
                                                                            )}
                                                                        </Row>
                                                                        <LemonDivider large/>
                                                                        {error && (
                                                                            <Row
                                                                                className='cohort-detail__matching-group__error-row'>
                                                                                <AlertMessage type='error' style={{width: "100%"}}>
                                                                                    <>
                                                                                        {error}
                                                                                    </>
                                                                                </AlertMessage>
                                                                            </Row>
                                                                        )}
                                                                        {kids}
                                                                    </div>
                                                                )
                                                            }}
                                                        >
                                                            <>
                                                                {group.values.map((criteria, criteriaIndex) => {
                                                                    return isCohortCriteriaGroup(criteria) ? null : (
                                                                        <Group key={criteriaIndex}
                                                                               name={["values", criteriaIndex]}>
                                                                            <CohortCriteriaRowBuilder
                                                                                groupIndex={groupIndex}
                                                                                index={criteriaIndex}
                                                                                logicalOperator={group.type}
                                                                                criteria={criteria}
                                                                                type={criteriaToBehavioralFilterType(
                                                                                    criteria
                                                                                )}
                                                                                onChange={setCriteria}
                                                                                onDuplicate={() =>
                                                                                    duplicateFilter(
                                                                                        groupIndex,
                                                                                        criteriaIndex
                                                                                    )
                                                                                }
                                                                                onRemove={() =>
                                                                                    removeFilter(
                                                                                        groupIndex,
                                                                                        criteriaIndex
                                                                                    )
                                                                                }
                                                                                hideDeleteIcon={
                                                                                    group.values.length <= 1
                                                                                }
                                                                            />
                                                                            {criteriaIndex ===
                                                                                group.values.length - 1 && (
                                                                                    <Row>
                                                                                        <LemonButton
                                                                                            data-attr={
                                                                                                'cohort-add-filter-group-criteria'
                                                                                            }
                                                                                            style={{margin: '0.75rem'}}
                                                                                            type="secondary"
                                                                                            onClick={() =>
                                                                                                addFilter(groupIndex)
                                                                                            }
                                                                                            icon={
                                                                                                <IconPlusMini
                                                                                                    color="var(--primary)"/>
                                                                                            }
                                                                                        >
                                                                                            Add criteria
                                                                                        </LemonButton>
                                                                                    </Row>
                                                                                )}
                                                                        </Group>
                                                                    )
                                                                })}
                                                            </>
                                                        </KeaField>
                                                    </Group>
                                                ) : null
                                            )}
                                            <LemonButton
                                                data-attr={`cohort-add-filter-group`}
                                                className="mb mt"
                                                type="secondary"
                                                onClick={() => addFilter()}
                                                icon={<IconPlusMini color="var(--primary)"/>}
                                                fullWidth
                                            >
                                                Add criteria group
                                            </LemonButton>
                                        </>
                                    ) : (
                                        <>
                                            {cohort.groups.map((group: CohortGroupType, index: number) => (
                                                <Group key={index} name={['groups', index]}>
                                                    <div
                                                        style={{
                                                            display: 'flex',
                                                            flexDirection: 'column',
                                                            alignItems: 'center',
                                                            width: '100%',
                                                        }}
                                                    >
                                                        <KeaField
                                                            name="id"
                                                            template={({ error, kids }) => {
                                                                return (
                                                                    <div
                                                                        style={{
                                                                            padding: 15,
                                                                            border: error
                                                                                ? '1px solid var(--danger)'
                                                                                : '1px solid rgba(0, 0, 0, 0.1)',
                                                                            borderRadius: 4,
                                                                            width: '100%',
                                                                        }}
                                                                    >
                                                                        {kids}
                                                                        <Row>
                                                                            {error && (
                                                                                <div
                                                                                    style={{
                                                                                        color: 'var(--danger)',
                                                                                        marginTop: 16,
                                                                                    }}
                                                                                >
                                                                                    {error}
                                                                                </div>
                                                                            )}
                                                                        </Row>
                                                                    </div>
                                                                )
                                                            }}
                                                        >
                                                            <MatchCriteriaSelector
                                                                onCriteriaChange={(newGroup) =>
                                                                    onCriteriaChange(newGroup, group.id)
                                                                }
                                                                onRemove={() => {
                                                                    setCohort({
                                                                        ...cohort,
                                                                        groups: cohort.groups.filter(
                                                                            (_, i) => i !== index
                                                                        ),
                                                                    })
                                                                }}
                                                                group={group}
                                                                hideRemove={cohort.groups.length === 1}
                                                            />
                                                        </KeaField>
                                                        {index < cohort.groups.length - 1 && (
                                                            <div className="stateful-badge or mt mb">OR</div>
                                                        )}
                                                    </div>
                                                </Group>
                                            ))}
                                            <span id="add" />
                                            <div style={{ marginTop: 8, marginBottom: 8 }}>
                                                <a
                                                    href="#add"
                                                    style={{ padding: 0 }}
                                                    onClick={() => {
                                                        setCohort({
                                                            ...cohort,
                                                            groups: [
                                                                ...cohort.groups,
                                                                {
                                                                    id: Math.random().toString().substr(2, 5),
                                                                    matchType: PROPERTY_MATCH_TYPE,
                                                                    properties: [],
                                                                },
                                                            ],
                                                        })
                                                    }}
                                                    data-attr="add-match-criteria"
                                                >
                                                    <PlusOutlined /> Add matching criteria
                                                </a>
                                            </div>
                                        </>
                                    )}
                                </>
                            </Col>
                        </Row>
                    </>
                )}

                {!isNewCohort && (
                    <>
                        <Divider />
                        <div>
                            <h3 className="l3">Persons in this cohort</h3>
                            {cohort.is_calculating ? (
                                <div className="cohort-recalculating flex-center">
                                    <Spinner size="sm" style={{ marginRight: 4 }} />
                                    We're recalculating who belongs to this cohort. This could take up to a couple of
                                    minutes.
                                </div>
                            ) : (
                                <div style={{ marginTop: 15 }}>
                                    <Persons cohort={cohort} />
                                </div>
                            )}
                        </div>
                    </>
                )}
            </VerticalForm>
        </div>
    )
}
