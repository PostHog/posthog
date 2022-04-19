import React, { useMemo } from 'react'
import { useActions, useValues } from 'kea'
import { CohortNameInput } from './CohortNameInput'
import { CohortDescriptionInput } from './CohortDescriptionInput'
import { Col, Divider, Row, Tooltip } from 'antd'
import { CohortMatchingCriteriaSection } from './CohortMatchingCriteriaSection'
import { AvailableFeature, CohortType } from '~/types'
import { COHORT_DYNAMIC, COHORT_STATIC } from 'lib/constants'
import { InboxOutlined, CalculatorOutlined, OrderedListOutlined } from '@ant-design/icons'
import Dragger from 'antd/lib/upload/Dragger'
import { CohortDetailsRow } from './CohortDetailsRow'
import { Persons } from 'scenes/persons/Persons'
import { cohortLogic } from './cohortLogic'
import { UploadFile } from 'antd/lib/upload/interface'
import { DropdownSelector } from 'lib/components/DropdownSelector/DropdownSelector'
import { userLogic } from 'scenes/userLogic'
import 'antd/lib/dropdown/style/index.css'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonButton } from 'lib/components/LemonButton'
import { PageHeader } from 'lib/components/PageHeader'

export const scene: SceneExport = {
    component: Cohort,
    logic: cohortLogic,
    paramsToProps: ({ params: { id } }): typeof cohortLogic['props'] => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
        pageKey: 0,
    }),
}

let uniqueMemoizedIndex = 0

export function Cohort({ id }: { id?: CohortType['id'] } = {}): JSX.Element {
    const pageKey = useMemo(() => uniqueMemoizedIndex++, [id])
    const logic = cohortLogic({ pageKey, id })
    const { setCohort, saveCohort, deleteCohort } = useActions(logic)
    const { cohort, submitted } = useValues(logic)
    const { hasAvailableFeature } = useValues(userLogic)

    const onDescriptionChange = (description: string): void => {
        setCohort({
            ...cohort,
            description,
        })
    }

    const onTypeChange = (type: string): void => {
        if (type === COHORT_STATIC) {
            setCohort({
                ...cohort,
                is_static: true,
            })
        } else if (type === COHORT_DYNAMIC) {
            setCohort({
                ...cohort,
                is_static: false,
            })
        }
    }

    const staticCSVDraggerProps = {
        name: 'file',
        multiple: false,
        fileList: cohort.csv ? [cohort.csv] : [],
        beforeUpload(file: UploadFile) {
            setCohort({ ...cohort, csv: file })

            return false
        },
        accept: '.csv',
    }

    const COHORT_TYPE_OPTIONS = [
        {
            key: COHORT_STATIC,
            label: 'Static',
            description: 'Upload a list of users. Updates manually',
            icon: <OrderedListOutlined />,
        },
        {
            key: COHORT_DYNAMIC,
            label: 'Dynamic',
            description: 'Cohort updates dynamically based on properties',
            icon: <CalculatorOutlined />,
        },
    ]

    const cohortTypeDropdown = (): JSX.Element => (
        <DropdownSelector
            options={COHORT_TYPE_OPTIONS}
            disabled={cohort.id !== 'new'}
            value={cohort.is_static ? COHORT_STATIC : COHORT_DYNAMIC}
            onValueChange={onTypeChange}
        />
    )

    return (
        <div className="cohort">
            <PageHeader
                title={cohort.id === 'new' ? 'New cohort' : cohort.name || 'Untitled'}
                buttons={
                    <div className="flex-center">
                        {cohort.id !== 'new' && (
                            <LemonButton
                                data-attr="delete-cohort"
                                status="danger"
                                type="secondary"
                                onClick={() => {
                                    deleteCohort()
                                }}
                                style={{ marginRight: 16 }}
                            >
                                Delete
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            data-attr="save-cohort"
                            htmlType="submit"
                            onClick={() => {
                                saveCohort()
                            }}
                        >
                            Save {cohort.id === 'new' ? 'cohort' : 'changes'}
                        </LemonButton>
                    </div>
                }
            />
            <Divider />
            <Row gutter={16}>
                <Col md={14}>
                    <CohortNameInput input={cohort.name} onChange={(name: string) => setCohort({ ...cohort, name })} />
                </Col>
                <Col md={10}>
                    {cohort.id === 'new' ? (
                        cohortTypeDropdown()
                    ) : (
                        <Tooltip title="Create a new cohort to use a different type of cohort.">
                            <div>{cohortTypeDropdown()}</div>
                        </Tooltip>
                    )}
                </Col>
            </Row>
            {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && (
                <Row gutter={16} className="mt">
                    <Col span={24}>
                        <CohortDescriptionInput description={cohort.description} onChange={onDescriptionChange} />
                    </Col>
                </Row>
            )}
            {cohort.id && cohort.id !== 'new' && <CohortDetailsRow cohort={cohort} />}
            <Divider />
            {cohort.is_static ? (
                <div>
                    <h3 className="l3">Add Users</h3>
                    <span>
                        Drop a <pre style={{ display: 'inline' }}>.csv</pre> file here to add users to your cohort
                    </span>
                    <Dragger {...staticCSVDraggerProps} className="cohort-csv-dragger">
                        <p className="ant-upload-drag-icon">
                            <InboxOutlined />
                        </p>
                        <div>
                            <p className="ant-upload-text">Click or drag file to this area to upload</p>
                            <p className="ant-upload-hint">
                                The CSV file only requires a single column with the user’s distinct ID.
                            </p>

                            {submitted && !cohort.csv && (
                                <p style={{ color: 'var(--danger)', marginTop: 16 }}>You need to upload a CSV file.</p>
                            )}
                        </div>
                    </Dragger>
                </div>
            ) : (
                <CohortMatchingCriteriaSection logic={logic} />
            )}

            {cohort.id !== 'new' && (
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
                                <Persons cohort={cohort.id} />
                            </div>
                        )}
                    </div>
                </>
            )}
        </div>
    )
}
