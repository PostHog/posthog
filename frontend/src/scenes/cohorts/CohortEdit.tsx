import { LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { UploadFile } from 'antd/es/upload/interface'
import Dragger from 'antd/lib/upload/Dragger'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { CohortTypeEnum } from 'lib/constants'
import { Field } from 'lib/forms/Field'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconUploadFile } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { pluralize } from 'lib/utils'
import { cohortEditLogic, CohortLogicProps } from 'scenes/cohorts/cohortEditLogic'
import { CohortCriteriaGroups } from 'scenes/cohorts/CohortFilters/CohortCriteriaGroups'
import { COHORT_TYPE_OPTIONS } from 'scenes/cohorts/CohortFilters/constants'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { Query } from '~/queries/Query/Query'
import { AvailableFeature, NotebookNodeType } from '~/types'

import { useIsReadonlyCohort } from './cohortUtils'

export function CohortEdit({ id }: CohortLogicProps): JSX.Element {
    const is3000 = useFeatureFlag('POSTHOG_3000')
    const logicProps = { id }
    const logic = cohortEditLogic(logicProps)
    const { deleteCohort, setOuterGroupsType, setQuery, duplicateCohort, setEditCohort } = useActions(logic)
    const { cohort, cohortLoading, cohortMissing, query, duplicatedCohortLoading } = useValues(logic)
    const { hasAvailableFeature } = useValues(userLogic)
    const readonly = useIsReadonlyCohort(logicProps)
    const isNewCohort = cohort.id === 'new' || cohort.id === undefined

    if (cohortMissing) {
        return <NotFound object="cohort" />
    }

    const pageHeaderTitle = isNewCohort ? 'New cohort' : cohort.name || 'Untitled'
    return (
        <div className="cohort">
            <Form id="cohort" logic={cohortEditLogic} props={logicProps} formKey="cohort" enableFormOnSubmit>
                <PageHeader
                    title={
                        <div className="flex items-center gap-2 mb-2">
                            {pageHeaderTitle}
                            <div className="flex">
                                <LemonTag type="highlight" className="uppercase">
                                    {cohort.is_static ? 'Static · Updated manually' : 'Dynamic . Updates automatically'}
                                </LemonTag>
                            </div>
                        </div>
                    }
                    description={
                        readonly && cohort.description ? (
                            <span style={{ fontStyle: 'normal' }}>{cohort.description}</span>
                        ) : (
                            ''
                        )
                    }
                    buttons={
                        <div className="flex items-center gap-2">
                            {!readonly ? (
                                <LemonButton
                                    data-attr="cancel-cohort"
                                    type="secondary"
                                    onClick={() => {
                                        if (isNewCohort) {
                                            router.actions.push(urls.cohorts())
                                        } else {
                                            setEditCohort(false)
                                        }
                                    }}
                                    disabled={cohortLoading}
                                >
                                    Cancel
                                </LemonButton>
                            ) : (
                                <>
                                    <More
                                        overlay={
                                            <>
                                                {!cohort.is_static && (
                                                    <>
                                                        <LemonButton
                                                            onClick={() => duplicateCohort(false)}
                                                            fullWidth
                                                            disabledReason={
                                                                cohort.is_calculating
                                                                    ? 'Cohort is still calculating'
                                                                    : undefined
                                                            }
                                                            loading={duplicatedCohortLoading}
                                                        >
                                                            Duplicate as dynamic cohort
                                                        </LemonButton>
                                                        <LemonButton
                                                            onClick={() => duplicateCohort(true)}
                                                            fullWidth
                                                            disabledReason={
                                                                cohort.is_calculating
                                                                    ? 'Cohort is still calculating'
                                                                    : undefined
                                                            }
                                                            loading={duplicatedCohortLoading}
                                                        >
                                                            Duplicate as static cohort
                                                        </LemonButton>
                                                        <LemonDivider />
                                                    </>
                                                )}
                                                <LemonButton
                                                    data-attr="delete-cohort"
                                                    fullWidth
                                                    status="danger"
                                                    onClick={() => {
                                                        deleteCohort()
                                                    }}
                                                >
                                                    Delete cohort
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                    <LemonDivider vertical />
                                </>
                            )}
                            {!isNewCohort && (
                                <NotebookSelectButton
                                    type="secondary"
                                    resource={{
                                        type: NotebookNodeType.Cohort,
                                        attrs: { id },
                                    }}
                                />
                            )}
                            {!readonly && (
                                <LemonButton
                                    type="primary"
                                    data-attr="save-cohort"
                                    htmlType="submit"
                                    loading={cohortLoading || cohort.is_calculating}
                                    form="cohort"
                                >
                                    Save
                                </LemonButton>
                            )}
                            {readonly && (
                                <LemonButton
                                    data-attr="edit-cohort"
                                    type="secondary"
                                    onClick={() => setEditCohort(true)}
                                >
                                    Edit
                                </LemonButton>
                            )}
                        </div>
                    }
                />
                {!readonly && (
                    <>
                        {!is3000 && <LemonDivider />}
                        <div className="space-y-2 max-w-160">
                            <div className="flex gap-4 flex-wrap">
                                <div className="flex-1">
                                    <Field name="name" label="Name">
                                        <LemonInput data-attr="cohort-name" />
                                    </Field>
                                </div>
                                {isNewCohort && (
                                    <div className="flex-1">
                                        <Field name="is_static" label="Type">
                                            {({ value, onChange }) => (
                                                <LemonSelect
                                                    options={COHORT_TYPE_OPTIONS}
                                                    value={value ? CohortTypeEnum.Static : CohortTypeEnum.Dynamic}
                                                    onChange={(cohortType) => {
                                                        onChange(cohortType === CohortTypeEnum.Static)
                                                    }}
                                                    fullWidth
                                                    data-attr="cohort-type"
                                                />
                                            )}
                                        </Field>
                                    </div>
                                )}
                                {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && (
                                    <div className="ph-ignore-input">
                                        <Field name="description" label="Description" data-attr="cohort-description">
                                            <LemonTextArea />
                                        </Field>
                                    </div>
                                )}
                            </div>
                        </div>
                    </>
                )}
                {cohort.is_static ? (
                    <div className="mt-4 ph-ignore-input">
                        <Field name="csv" label={isNewCohort ? 'Upload users' : 'Add users'} data-attr="cohort-csv">
                            {({ onChange }) => (
                                <>
                                    <span>
                                        Upload a CSV file to add users to your cohort. The CSV file only requires a
                                        single column with the user’s distinct ID. The very first row (the header) will
                                        be skipped during import.
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
                        <LemonDivider className="my-6" />
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
                                suffix={['criterion', 'criteria']}
                                readOnly={readonly}
                            />
                        </div>
                        <CohortCriteriaGroups id={logicProps.id} />
                    </>
                )}

                {/* The typeof here is needed to pass the cohort id to the query below. Using `isNewCohort` won't work */}
                {typeof cohort.id === 'number' && (
                    <>
                        <LemonDivider className="my-6" />
                        <div>
                            <h3 className="l3 mb-4">
                                Persons in this cohort
                                <span className="text-muted ml-2">
                                    {!cohort.is_calculating &&
                                        `(${cohort.count} matching ${pluralize(
                                            cohort.count ?? 0,
                                            'person',
                                            'persons',
                                            false
                                        )})`}
                                </span>
                            </h3>
                            {cohort.is_calculating ? (
                                <div className="cohort-recalculating flex items-center">
                                    <Spinner className="mr-4" />
                                    We're recalculating who belongs to this cohort. This could take up to a couple of
                                    minutes.
                                </div>
                            ) : (
                                <Query query={query} setQuery={setQuery} />
                            )}
                        </div>
                    </>
                )}
            </Form>
        </div>
    )
}
