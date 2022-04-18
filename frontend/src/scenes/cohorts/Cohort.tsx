import React, { useMemo, useState } from 'react'
import { useActions, useValues } from 'kea'
import { Col, Divider, Row } from 'antd'
import { CohortMatchingCriteriaSection } from './CohortMatchingCriteriaSection'
import { AvailableFeature, CohortType } from '~/types'
import { CohortTypeType } from 'lib/constants'
import { CalculatorOutlined, LoadingOutlined, OrderedListOutlined } from '@ant-design/icons'
import Dragger from 'antd/lib/upload/Dragger'
import { CohortDetailsRow } from './CohortDetailsRow'
import { Persons } from 'scenes/persons/Persons'
import { cohortLogic } from './cohortLogic'
import { userLogic } from 'scenes/userLogic'
import 'antd/lib/dropdown/style/index.css'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonButton } from 'lib/components/LemonButton'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonInput } from 'lib/components/LemonInput'
import { Field } from 'lib/forms/Field'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { LemonSelect, LemonSelectOptions } from 'lib/components/LemonSelect'
import { LemonTextArea } from 'lib/components/LemonTextArea'
import { IconUploadFile } from 'lib/components/icons'

export const scene: SceneExport = {
    component: Cohort,
    logic: cohortLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id && id !== 'new' ? parseInt(id) : 'new', pageKey: 0 }),
}

const COHORT_TYPE_OPTIONS: LemonSelectOptions = {
    [CohortTypeType.Static]: {
        label: 'Static · Updated manually',
        icon: <OrderedListOutlined />,
    },
    [CohortTypeType.Dynamic]: {
        label: 'Dynamic · Updates automatically',
        icon: <CalculatorOutlined />,
    },
}

let uniqueMemoizedIndex = 0

export function Cohort({ id }: { id?: CohortType['id'] } = {}): JSX.Element {
    const pageKey = useMemo(() => uniqueMemoizedIndex++, [id])
    const logicProps = { pageKey, id }
    const logic = cohortLogic(logicProps)
    const { deleteCohort, cancelCohort } = useActions(logic)
    const { cohort } = useValues(logic)
    const { hasAvailableFeature } = useValues(userLogic)
    const [csvUploading, setCsvUploading] = useState<boolean>(false)
    const isNewCohort = cohort.id === 'new'

    console.log('COHORT', cohort)

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
                                        cancelCohort()
                                    }}
                                    style={{ marginRight: 8 }}
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
                                >
                                    Delete
                                </LemonButton>
                            )}
                            <LemonButton type="primary" data-attr="save-cohort" htmlType="submit">
                                Save
                            </LemonButton>
                        </div>
                    }
                />
                <Divider />
                <Row gutter={[16, 24]} style={{ maxWidth: 640 }}>
                    <Col xs={24} sm={12}>
                        <Field name="name" label="Name">
                            {({ value, onValueChange }) => <LemonInput value={value} onChange={onValueChange} />}
                        </Field>
                    </Col>
                    <Col xs={24} sm={12}>
                        <Field name="is_static" label="Type">
                            {({ value, onValueChange }) => (
                                <LemonSelect
                                    options={COHORT_TYPE_OPTIONS}
                                    value={value ? CohortTypeType.Static : CohortTypeType.Dynamic}
                                    onChange={(cohortType) => {
                                        onValueChange(cohortType === CohortTypeType.Static)
                                    }}
                                    type="stealth"
                                    outlined
                                    style={{ width: '100%' }}
                                />
                            )}
                        </Field>
                    </Col>
                </Row>
                {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && (
                    <Row gutter={[16, 24]} className="mt" style={{ maxWidth: 640 }}>
                        <Col span={24}>
                            <Field name="description" label="Description">
                                {({ value, onValueChange }) => <LemonTextArea value={value} onChange={onValueChange} />}
                            </Field>
                        </Col>
                    </Row>
                )}
                {cohort.id && !isNewCohort && <CohortDetailsRow cohort={cohort} />}
                {cohort.is_static ? (
                    <Row gutter={24} className="mt">
                        <Col span={24}>
                            <Field name={['csv', 'uid']} label="Upload users">
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
                                            showUploadList
                                            onChange={({ file, fileList }) => {
                                                console.log('ONCHANGE', file, fileList)
                                                if (file.status === 'uploading') {
                                                    setCsvUploading(true)
                                                    return
                                                }
                                                if (file.status === 'done') {
                                                    onValueChange(file)
                                                    setCsvUploading(false)
                                                }
                                            }}
                                            // onRemove={() => {
                                            //     onValueChange({})
                                            // }}
                                            className="cohort-csv-dragger"
                                        >
                                            {csvUploading ? (
                                                <>
                                                    <LoadingOutlined style={{ fontSize: '3rem' }} />
                                                    <div className="ant-upload-text">Uploading file...</div>
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
                    <CohortMatchingCriteriaSection logic={logic} />
                )}

                {!isNewCohort && (
                    <>
                        <Divider />
                        <div>
                            <h3 className="l3">Matched Users</h3>
                            <span>List of users that currently match the criteria defined</span>
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
