import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { useActions, useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { CohortLogicProps } from 'scenes/cohorts/cohortLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/components/LemonButton'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Divider } from 'antd'
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
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { Form } from 'kea-forms'

export function CohortEdit({ id }: CohortLogicProps): JSX.Element {
    const logicProps = { id }
    const logic = cohortEditLogic(logicProps)
    const { deleteCohort, setOuterGroupsType } = useActions(logic)
    const { cohort, cohortLoading } = useValues(logic)
    const { hasAvailableFeature } = useValues(userLogic)
    const isNewCohort = cohort.id === 'new' || cohort.id === undefined

    return (
        <div className="cohort">
            <Form logic={cohortEditLogic} props={logicProps} formKey="cohort" enableFormOnSubmit>
                <PageHeader
                    title={isNewCohort ? 'New cohort' : cohort.name || 'Untitled'}
                    buttons={
                        <div className="flex items-center gap-2">
                            {isNewCohort ? (
                                <LemonButton
                                    data-attr="cancel-cohort"
                                    type="secondary"
                                    onClick={() => {
                                        router.actions.push(urls.cohorts())
                                    }}
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
                <div className="space-y-2" style={{ maxWidth: 640 }}>
                    <div className="flex gap-4 flex-wrap" data-tooltip="cohorts-type">
                        <div className="flex-1">
                            <Field name="name" label="Name">
                                <LemonInput data-attr="cohort-name" />
                            </Field>
                        </div>
                        <div className="flex-1">
                            <Field name="is_static" label="Type">
                                {({ value, onChange }) => (
                                    <Tooltip
                                        title={
                                            isNewCohort
                                                ? null
                                                : 'Create a new cohort to use a different type of cohort.'
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
                                                type="secondary"
                                                status="stealth"
                                                fullWidth
                                                data-attr="cohort-type"
                                            />
                                        </div>
                                    </Tooltip>
                                )}
                            </Field>
                        </div>
                    </div>
                    {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && (
                        <div className="ph-ignore-input">
                            <Field name="description" label="Description" data-attr="cohort-description">
                                <LemonTextArea />
                            </Field>
                        </div>
                    )}
                </div>
                {cohort.is_static ? (
                    <div className="mt-4 ph-ignore-input">
                        <Field name="csv" label={isNewCohort ? 'Upload users' : 'Add users'} data-attr="cohort-csv">
                            {({ onChange }) => (
                                <>
                                    <span>
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
                    </div>
                ) : (
                    <>
                        <Divider />
                        <div className="flex items-center justify-between my-4">
                            <div className="flex flex-col">
                                <LemonLabel htmlFor="groups">Matching criteria</LemonLabel>
                                <span>
                                    Actors who match the following criteria will be part of the cohort. Continuously
                                    updated automatically.
                                </span>
                            </div>
                            <AndOrFilterSelect
                                value={cohort.filters.properties.type}
                                onChange={(value) => {
                                    setOuterGroupsType(value)
                                }}
                                topLevelFilter={true}
                                suffix="criteria"
                            />
                        </div>
                        <CohortCriteriaGroups id={logicProps.id} />
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
                                <Persons cohort={cohort.id} />
                            )}
                        </div>
                    </>
                )}
            </Form>
        </div>
    )
}
