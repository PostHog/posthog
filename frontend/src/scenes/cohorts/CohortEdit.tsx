import { LemonBanner, LemonDivider, LemonFileInput, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { CohortTypeEnum } from 'lib/constants'
import { IconErrorOutline, IconUploadFile } from 'lib/lemon-ui/icons'
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

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { Query } from '~/queries/Query/Query'
import { NotebookNodeType } from '~/types'

export function CohortEdit({ id }: CohortLogicProps): JSX.Element {
    const logicProps = { id }
    const logic = cohortEditLogic(logicProps)
    const { deleteCohort, setOuterGroupsType, setQuery, duplicateCohort } = useActions(logic)
    const { cohort, cohortLoading, cohortMissing, query, duplicatedCohortLoading } = useValues(logic)
    const isNewCohort = cohort.id === 'new' || cohort.id === undefined

    if (cohortMissing) {
        return <NotFound object="cohort" />
    }

    if (cohortLoading) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton active className="h-4 w-2/5" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-3/5" />
            </div>
        )
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
                <div className="deprecated-space-y-2 max-w-200">
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
                        {!isNewCohort && !cohort?.is_static && (
                            <div className="max-w-70 w-fit">
                                <div className="flex gap-1 flex-col">
                                    <LemonLabel>Last calculated</LemonLabel>
                                    {cohort.is_calculating ? (
                                        <div className="text-s">In progress...</div>
                                    ) : cohort.last_calculation ? (
                                        <div className="flex flex-1 flex-row gap-1">
                                            <TZLabel time={cohort.last_calculation} />
                                            {cohort.errors_calculating ? (
                                                <Tooltip
                                                    title={
                                                        "The last attempted calculation failed. This means your current cohort data can be stale. This doesn't affect feature flag evaluation."
                                                    }
                                                >
                                                    <div className="text-danger">
                                                        <IconErrorOutline className="text-danger text-xl shrink-0" />
                                                    </div>
                                                </Tooltip>
                                            ) : null}
                                        </div>
                                    ) : (
                                        <div className="text-s">Not yet calculated</div>
                                    )}
                                    <div className="text-secondary text-xs">
                                        Cohorts are recalculated every 24 hours
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                    <div className="ph-ignore-input">
                        <LemonField name="description" label="Description" data-attr="cohort-description">
                            <LemonTextArea />
                        </LemonField>
                    </div>
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
                                            <div className="flex flex-col items-center justify-center flex-1 cohort-csv-dragger text-text-3000 deprecated-space-y-1">
                                                {cohort.csv ? (
                                                    <>
                                                        <IconUploadFile
                                                            style={{ fontSize: '3rem', color: 'var(--text-secondary)' }}
                                                        />
                                                        <div>{cohort.csv?.name ?? 'File chosen'}</div>
                                                    </>
                                                ) : (
                                                    <>
                                                        <IconUploadFile
                                                            style={{ fontSize: '3rem', color: 'var(--text-secondary)' }}
                                                        />
                                                        <div>Drag a file here or click to browse for a file</div>
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
                        {!isNewCohort && cohort.experiment_set && cohort.experiment_set.length > 0 && (
                            <LemonBanner type="info">
                                This cohort manages exposure for an experiment. Editing this cohort may change
                                experiment metrics. If unsure,{' '}
                                <Link to={urls.experiment(cohort.experiment_set[0])}>
                                    check the experiment details.
                                </Link>
                            </LemonBanner>
                        )}
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
                                <span className="text-secondary ml-2">
                                    {!cohort.is_calculating &&
                                        cohort.count !== undefined &&
                                        `(${cohort.count} matching ${pluralize(
                                            cohort.count,
                                            'person',
                                            'persons',
                                            false
                                        )})`}
                                </span>
                            </h3>
                            {cohort.is_calculating ? (
                                <div className="cohort-recalculating flex items-center">
                                    <Spinner className="mr-4" />
                                    {cohort.is_static
                                        ? "We're creating this cohort. This could take up to a couple of minutes."
                                        : "We're recalculating who belongs to this cohort. This could take up to a couple of minutes."}
                                </div>
                            ) : (
                                <Query
                                    query={query}
                                    setQuery={setQuery}
                                    context={{ refresh: 'force_blocking', fileNameForExport: cohort.name }}
                                />
                            )}
                        </div>
                    </>
                )}
            </Form>
        </div>
    )
}
