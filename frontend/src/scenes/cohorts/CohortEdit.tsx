import { LemonDivider, LemonFileInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { CohortTypeEnum } from 'lib/constants'
import { IconUploadFile } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
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

export function CohortEdit({ id }: CohortLogicProps): JSX.Element {
    const logicProps = { id }
    const logic = cohortEditLogic(logicProps)
    const { deleteCohort, setOuterGroupsType, setQuery, duplicateCohort } = useActions(logic)
    const { cohort, cohortLoading, cohortMissing, query, duplicatedCohortLoading } = useValues(logic)
    const { hasAvailableFeature } = useValues(userLogic)
    const isNewCohort = cohort.id === 'new' || cohort.id === undefined

    if (cohortMissing) {
        return <NotFound object="cohort" />
    }
    return (
        <div className="cohort">
            <Form id="cohort" logic={cohortEditLogic} props={logicProps} formKey="cohort" enableFormOnSubmit>
                <PageHeader
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
                                                onClick={deleteCohort}
                                            >
                                                Delete cohort
                                            </LemonButton>
                                        </>
                                    }
                                />
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
                            <LemonButton
                                type="primary"
                                data-attr="save-cohort"
                                htmlType="submit"
                                loading={cohortLoading || cohort.is_calculating}
                                form="cohort"
                            >
                                Save
                            </LemonButton>
                        </div>
                    }
                />
                <div className="space-y-2 max-w-160">
                    <div className="flex gap-4 flex-wrap">
                        <div className="flex-1">
                            <LemonField name="name" label="Name">
                                <LemonInput data-attr="cohort-name" />
                            </LemonField>
                        </div>
                        <div className="flex-1">
                            <LemonField name="is_static" label="Type">
                                {({ value, onChange }) => (
                                    <LemonSelect
                                        disabledReason={
                                            isNewCohort
                                                ? null
                                                : 'Create a new cohort to use a different type of cohort.'
                                        }
                                        options={COHORT_TYPE_OPTIONS}
                                        value={value ? CohortTypeEnum.Static : CohortTypeEnum.Dynamic}
                                        onChange={(cohortType) => {
                                            onChange(cohortType === CohortTypeEnum.Static)
                                        }}
                                        fullWidth
                                        data-attr="cohort-type"
                                    />
                                )}
                            </LemonField>
                        </div>
                    </div>
                    {hasAvailableFeature(AvailableFeature.DASHBOARD_COLLABORATION) && (
                        <div className="ph-ignore-input">
                            <LemonField name="description" label="Description" data-attr="cohort-description">
                                <LemonTextArea />
                            </LemonField>
                        </div>
                    )}
                </div>
                {cohort.is_static ? (
                    <div className="mt-4 ph-ignore-input">
                        <LemonField
                            name="csv"
                            label={isNewCohort ? 'Upload users' : 'Add users'}
                            data-attr="cohort-csv"
                        >
                            {({ onChange }) => (
                                <>
                                    <span>
                                        Upload a CSV file to add users to your cohort. The CSV file only requires a
                                        single column with the user’s distinct ID. The very first row (the header) will
                                        be skipped during import.
                                    </span>
                                    <LemonFileInput
                                        accept=".csv"
                                        multiple={false}
                                        value={cohort.csv ? [cohort.csv] : []}
                                        onChange={(files) => onChange(files[0])}
                                        showUploadedFiles={false}
                                        callToAction={
                                            <div className="flex flex-col items-center justify-center flex-1 cohort-csv-dragger text-default space-y-1">
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
                                            </div>
                                        }
                                    />
                                </>
                            )}
                        </LemonField>
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
