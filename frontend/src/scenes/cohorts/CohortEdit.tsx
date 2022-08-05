import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { CohortLogicProps } from 'scenes/cohorts/cohortLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/components/LemonButton'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Col, Divider, Row } from 'antd'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonSelect } from 'lib/components/LemonSelect'
import { COHORT_TYPE_OPTIONS } from 'scenes/cohorts/CohortFilters/constants'
import { CohortTypeEnum } from 'lib/constants'
import { AvailableFeature } from '~/types'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import Dragger from 'antd/lib/upload/Dragger'
import { UploadFile } from 'antd/es/upload/interface'
import { IconUploadFile } from 'lib/components/icons'
import { AndOrFilterSelect } from 'lib/components/PropertyGroupFilters/PropertyGroupFilters'
import { CohortCriteriaGroups } from 'scenes/cohorts/CohortFilters/CohortCriteriaGroups'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { Persons } from 'scenes/persons/Persons'
import React from 'react'

export function CohortEdit({ id }: CohortLogicProps): JSX.Element {
    const logicProps = { id }
    const logic = cohortEditLogic(logicProps)
    const { deleteCohort, setOuterGroupsType } = useActions(logic)
    const { cohort, cohortLoading } = useValues(logic)
    const { hasAvailableFeature } = useValues(userLogic)
    const isNewCohort = cohort.id === 'new' || cohort.id === undefined

    return (
        <div className="cohort">
            <VerticalForm logic={cohortEditLogic} props={logicProps} formKey="cohort" enableFormOnSubmit>
                <PageHeader
                    title={isNewCohort ? 'New cohort' : cohort.name || 'Untitled'}
                    buttons={
                        <div className="flex items-center">
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
                                loading={cohortLoading || cohort.is_calculating}
                                disabled={cohortLoading || cohort.is_calculating}
                            >
                                Save
                            </LemonButton>
                        </div>
                    }
                />
                <Divider />
                <Row gutter={[16, 24]} style={{ maxWidth: 640 }} data-tooltip="cohorts-type">
                    <Col xs={24} sm={12}>
                        <Field name="name" label="Name" className="Cohort__Name">
                            <LemonInput data-attr="cohort-name" />
                        </Field>
                    </Col>
                    <Col xs={24} sm={12}>
                        <Field name="is_static" label="Type">
                            {({ value, onChange }) => (
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
                                                onChange(cohortType === CohortTypeEnum.Static)
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
                    <Row gutter={[16, 24]} className="mt-4 ph-ignore-input" style={{ maxWidth: 640 }}>
                        <Col span={24}>
                            <Field name="description" label="Description" data-attr="cohort-description">
                                <LemonTextArea />
                            </Field>
                        </Col>
                    </Row>
                )}
                {cohort.is_static ? (
                    <Row gutter={24} className="mt-4 ph-ignore-input">
                        <Col span={24}>
                            <Field name="csv" label={isNewCohort ? 'Upload users' : 'Add users'} data-attr="cohort-csv">
                                {({ onChange }) => (
                                    <>
                                        <span className="mb-4">
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
                                                onChange(file)
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
                        <Row gutter={24} className="mt-4">
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
                                        <Row align="middle" wrap={false} justify="space-between" className="pl-4">
                                            <AndOrFilterSelect
                                                value={cohort.filters.properties.type}
                                                onChange={(value) => {
                                                    setOuterGroupsType(value)
                                                }}
                                                topLevelFilter={true}
                                                suffix="criteria"
                                            />
                                        </Row>
                                    </Row>
                                    <CohortCriteriaGroups id={logicProps.id} />
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
                                <div className="cohort-recalculating flex items-center">
                                    <Spinner size="sm" style={{ marginRight: 4 }} />
                                    We're recalculating who belongs to this cohort. This could take up to a couple of
                                    minutes.
                                </div>
                            ) : (
                                <div style={{ marginTop: 15 }}>
                                    <Persons cohort={cohort.id} />
                                </div>
                            )}
                        </div>
                    </>
                )}
            </VerticalForm>
        </div>
    )
}
