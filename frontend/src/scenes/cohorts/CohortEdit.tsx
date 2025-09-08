import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconCopy, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonDivider, LemonFileInput, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneAddToNotebookDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToNotebookDropdownMenu'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { TZLabel } from 'lib/components/TZLabel'
import { CohortTypeEnum, FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconErrorOutline, IconUploadFile } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { pluralize } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { CohortCriteriaGroups } from 'scenes/cohorts/CohortFilters/CohortCriteriaGroups'
import { COHORT_TYPE_OPTIONS } from 'scenes/cohorts/CohortFilters/constants'
import { CohortLogicProps, cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { NotebookSelectButton } from 'scenes/notebooks/NotebookSelectButton/NotebookSelectButton'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelActions, ScenePanelDivider, ScenePanelMetaInfo } from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'

import { AddPersonToCohortModal } from './AddPersonToCohortModal'
import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'
import { createCohortDataNodeLogicKey } from './cohortUtils'

const RESOURCE_TYPE = 'cohort'

export function CohortEdit({ id }: CohortLogicProps): JSX.Element {
    const logicProps = { id }

    const logic = cohortEditLogic(logicProps)
    const { deleteCohort, setOuterGroupsType, setQuery, duplicateCohort, setCohortValue } = useActions(logic)
    const modalLogic = addPersonToCohortModalLogic(logicProps)
    const { showAddPersonToCohortModal } = useActions(modalLogic)
    const { cohort, cohortLoading, cohortMissing, query, duplicatedCohortLoading } = useValues(logic)
    const isNewCohort = cohort.id === 'new' || cohort.id === undefined
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]
    const dataNodeLogicKey = createCohortDataNodeLogicKey(cohort.id)

    if (cohortMissing) {
        return <NotFound object="cohort" />
    }

    if (cohortLoading && !newSceneLayout) {
        return (
            <div className="flex flex-col gap-y-2">
                <LemonSkeleton active className="h-4 w-2/5" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-full" />
                <LemonSkeleton active className="h-4 w-3/5" />
            </div>
        )
    }
    return (
        <div className="cohort">
            <AddPersonToCohortModal id={id} />
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
                            <>
                                {!newSceneLayout && (
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
                            </>
                        )}
                        {!isNewCohort && !newSceneLayout && (
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

            <ScenePanel>
                <ScenePanelMetaInfo>
                    <SceneFile dataAttrKey={RESOURCE_TYPE} />
                </ScenePanelMetaInfo>

                <ScenePanelDivider />

                <ScenePanelActions>
                    <SceneAddToNotebookDropdownMenu
                        dataAttrKey={RESOURCE_TYPE}
                        disabledReasons={{
                            'Save the cohort first': isNewCohort,
                        }}
                    />

                    <ButtonPrimitive
                        onClick={() => duplicateCohort(false)}
                        disabledReasons={{
                            'Save the cohort first': isNewCohort,
                            'Cohort must be static to duplicate': !cohort.is_static,
                            'Cohort is still calculating': cohort.is_calculating ?? false,
                        }}
                        menuItem
                    >
                        <IconCopy /> Duplicate as dynamic cohort
                    </ButtonPrimitive>

                    <ButtonPrimitive
                        onClick={() => duplicateCohort(true)}
                        disabledReasons={{
                            'Save the cohort first': isNewCohort,
                            'Cohort must be static to duplicate': !cohort.is_static,
                            'Cohort is still calculating': cohort.is_calculating ?? false,
                        }}
                        menuItem
                    >
                        <IconCopy /> Duplicate as static cohort
                    </ButtonPrimitive>

                    <ScenePanelDivider />

                    <ButtonPrimitive
                        onClick={() => {
                            deleteCohort()
                        }}
                        variant="danger"
                        menuItem
                        data-attr={`${RESOURCE_TYPE}-delete`}
                    >
                        <IconTrash />
                        Delete
                    </ButtonPrimitive>
                </ScenePanelActions>
            </ScenePanel>

            <Form id="cohort" logic={cohortEditLogic} props={logicProps} formKey="cohort" enableFormOnSubmit>
                <SceneContent>
                    <SceneTitleSection
                        name={cohort.name}
                        description={cohort.description || ''}
                        resourceType={{
                            to: urls.cohorts(),
                            type: RESOURCE_TYPE,
                        }}
                        isLoading={cohortLoading}
                        onNameChange={(value) => {
                            setCohortValue('name', value)
                        }}
                        onDescriptionChange={(value) => {
                            setCohortValue('description', value)
                        }}
                        docsURL="https://posthog.com/docs/data/cohorts"
                        canEdit
                        forceEdit={isNewCohort}
                    />

                    <SceneDivider />

                    <SceneSection
                        title="Type"
                        description="Static cohorts are created once and never updated, while dynamic cohorts are recalculated based on the latest data."
                        className={cn('max-w-200', {
                            'deprecated-space-y-2 ': !newSceneLayout,
                            'flex flex-col gap-y-2': newSceneLayout,
                        })}
                        hideTitleAndDescription
                    >
                        <div className="flex gap-4 flex-wrap">
                            {!newSceneLayout && (
                                <div className="flex-1">
                                    <LemonField name="name" label="Name">
                                        <LemonInput data-attr="cohort-name" />
                                    </LemonField>
                                </div>
                            )}
                            <div className={cn('flex-1', newSceneLayout && 'flex flex-col gap-y-4')}>
                                <LemonField name="is_static" label={newSceneLayout ? null : 'Type'}>
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

                                {newSceneLayout && !isNewCohort && !cohort?.is_static && (
                                    <div className="max-w-70 w-fit">
                                        <p className="flex items-center gap-x-1 my-0">
                                            <strong>Last calculated:</strong>
                                            {cohort.is_calculating ? (
                                                <WrappingLoadingSkeleton>In progress...</WrappingLoadingSkeleton>
                                            ) : cohort.last_calculation ? (
                                                <TZLabel time={cohort.last_calculation} />
                                            ) : (
                                                <>Not yet calculated</>
                                            )}
                                        </p>

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
                                )}
                            </div>
                            {!newSceneLayout && !isNewCohort && !cohort?.is_static && (
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
                        {!newSceneLayout && (
                            <div className="ph-ignore-input">
                                <LemonField name="description" label="Description" data-attr="cohort-description">
                                    <LemonTextArea />
                                </LemonField>
                            </div>
                        )}
                    </SceneSection>
                    {cohort.is_static ? (
                        <>
                            <SceneDivider />
                            <SceneSection
                                title={isNewCohort ? 'Upload users' : 'Add users'}
                                description={
                                    isNewCohort
                                        ? `Upload a CSV file to add users to your cohort. For single-column files, include
                                        one distinct ID per row (all rows will be processed as data). For multi-column
                                        files, include a header row with a 'distinct_id' column containing the user
                                        identifiers.`
                                        : undefined
                                }
                                className={cn('ph-ignore-input', !newSceneLayout && 'mt-4')}
                            >
                                {!isNewCohort && newSceneLayout && (
                                    <div className="flex flex-col gap-y-0 flex-1 justify-center">
                                        <h3 className="text-sm">Upload a CSV</h3>
                                        <span className="max-w-prose">
                                            Upload a CSV file to add users to your cohort. For single-column files,
                                            include one distinct ID per row (all rows will be processed as data). For
                                            multi-column files, include a header row with a 'distinct_id' column
                                            containing the user identifiers.
                                        </span>
                                    </div>
                                )}
                                {/* TODO: @adamleithp Allow users to download a template CSV file */}
                                {/* TODO: @adamleithp Tell users that adding ANOTHER file will NOT(?) replace the current one */}
                                {/* TODO: @adamleithp Render the csv file and validate it */}
                                {/* TODO: @adamleithp Adding a csv file doesn't show up with cohort.csv... */}
                                <LemonField
                                    name="csv"
                                    label={newSceneLayout ? null : isNewCohort ? null : 'Upload users'}
                                    data-attr="cohort-csv"
                                >
                                    {({ onChange }) => (
                                        <>
                                            {!newSceneLayout && !isNewCohort && (
                                                <span>
                                                    Upload a CSV file to add users to your cohort. For single-column
                                                    files, include one distinct ID per row (all rows will be processed
                                                    as data). Fo`r multi-column files, include a header row with a
                                                    'distinct_id' column containing the user identifiers.
                                                </span>
                                            )}
                                            <LemonFileInput
                                                accept=".csv"
                                                multiple={false}
                                                value={cohort.csv ? [cohort.csv] : []}
                                                onChange={(files) => onChange(files[0])}
                                                showUploadedFiles={false}
                                                callToAction={
                                                    <div
                                                        className={cn(
                                                            'flex flex-col items-center justify-center flex-1 cohort-csv-dragger text-text-3000 deprecated-space-y-1',
                                                            newSceneLayout &&
                                                                'text-primary mt-0 bg-transparent border border-dashed border-primary hover:border-secondary p-8',
                                                            newSceneLayout && cohort.csv?.name && 'border-success'
                                                        )}
                                                    >
                                                        {cohort.csv ? (
                                                            <>
                                                                <IconUploadFile
                                                                    style={{
                                                                        fontSize: '3rem',
                                                                        color: !newSceneLayout
                                                                            ? 'var(--color-text-secondary)'
                                                                            : 'var(--color-text-primary)',
                                                                    }}
                                                                />
                                                                <div>{cohort.csv?.name ?? 'File chosen'}</div>
                                                            </>
                                                        ) : (
                                                            <>
                                                                <IconUploadFile
                                                                    style={{
                                                                        fontSize: '3rem',
                                                                        color: !newSceneLayout
                                                                            ? 'var(--color-text-secondary)'
                                                                            : 'var(--color-text-primary)',
                                                                    }}
                                                                />
                                                                <div>
                                                                    Drag a file here or click to browse for a file
                                                                </div>
                                                                {newSceneLayout && (
                                                                    <div className="text-secondary text-xs">
                                                                        Accepts .csv files only
                                                                    </div>
                                                                )}
                                                            </>
                                                        )}
                                                    </div>
                                                }
                                            />
                                        </>
                                    )}
                                </LemonField>
                            </SceneSection>
                            {!isNewCohort && (
                                <>
                                    <LemonDivider label="OR" />
                                    <div>
                                        <h3 className="text-sm">Add users manually</h3>
                                        <span className="max-w-prose">
                                            Select the users that you would like to add to the cohort.
                                        </span>
                                        <LemonButton
                                            className="w-fit mt-4"
                                            type="primary"
                                            onClick={showAddPersonToCohortModal}
                                        >
                                            Add Users
                                        </LemonButton>
                                    </div>
                                </>
                            )}
                        </>
                    ) : (
                        <>
                            {!newSceneLayout ? <LemonDivider /> : <SceneDivider />}
                            {!isNewCohort && cohort.experiment_set && cohort.experiment_set.length > 0 && (
                                <LemonBanner type="info">
                                    This cohort manages exposure for an experiment. Editing this cohort may change
                                    experiment metrics. If unsure,{' '}
                                    <Link to={urls.experiment(cohort.experiment_set[0])}>
                                        check the experiment details.
                                    </Link>
                                </LemonBanner>
                            )}
                            <SceneSection
                                // TODO: @adamleithp Add a number of matching persons to the title "Matching criteria (100)"
                                title="Matching criteria"
                                description="Actors who match the following criteria will be part of the cohort. Continuously updated automatically."
                                className={cn('flex items-start justify-between')}
                                hideTitleAndDescription
                            >
                                {!newSceneLayout && (
                                    <div className="flex flex-col">
                                        <LemonLabel htmlFor="groups">Matching criteria</LemonLabel>
                                        <span>
                                            Actors who match the following criteria will be part of the cohort.
                                            Continuously updated automatically.
                                        </span>
                                    </div>
                                )}
                                <AndOrFilterSelect
                                    value={cohort.filters.properties.type}
                                    onChange={(value) => {
                                        setOuterGroupsType(value)
                                    }}
                                    topLevelFilter={true}
                                    suffix={['criterion', 'criteria']}
                                />
                                <div className={cn('w-full', newSceneLayout && '[&>div]:my-0 [&>div]:w-full')}>
                                    <CohortCriteriaGroups id={logicProps.id} />
                                </div>
                            </SceneSection>
                        </>
                    )}

                    {/* The typeof here is needed to pass the cohort id to the query below. Using `isNewCohort` won't work */}
                    {typeof cohort.id === 'number' && (
                        <>
                            <SceneDivider />
                            <SceneSection
                                title={
                                    <>
                                        Persons in this cohort
                                        <span className="text-secondary ml-2">
                                            {!cohort.is_calculating &&
                                                cohort.count !== undefined &&
                                                `(${cohort.count})`}
                                        </span>
                                    </>
                                }
                                description="Persons who match the following criteria will be part of the cohort."
                                hideTitleAndDescription
                            >
                                {!newSceneLayout && <LemonDivider />}
                                <div>
                                    {!newSceneLayout && (
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
                                    )}
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
                                            context={{
                                                refresh: 'force_blocking',
                                                fileNameForExport: cohort.name,
                                                dataNodeLogicKey: dataNodeLogicKey,
                                            }}
                                        />
                                    )}
                                </div>
                            </SceneSection>
                        </>
                    )}
                </SceneContent>
            </Form>
        </div>
    )
}
