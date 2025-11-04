import { BindLogic, BuiltLogic, Logic, LogicWrapper, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconClock, IconCopy, IconMinusSmall, IconPlusSmall, IconTrash, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonDialog, LemonDivider, LemonFileInput, Link, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneAddToNotebookDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToNotebookDropdownMenu'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { TZLabel } from 'lib/components/TZLabel'
import { CohortTypeEnum, FEATURE_FLAGS } from 'lib/constants'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconErrorOutline, IconRefresh, IconUploadFile } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { CohortCriteriaGroups } from 'scenes/cohorts/CohortFilters/CohortCriteriaGroups'
import { COHORT_TYPE_OPTIONS } from 'scenes/cohorts/CohortFilters/constants'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { urls } from 'scenes/urls'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { QueryContext } from '~/queries/types'
import { CohortType } from '~/types'

import { AddPersonToCohortModal } from './AddPersonToCohortModal'
import { PersonDisplayNameType, RemovePersonFromCohortButton } from './RemovePersonFromCohortButton'
import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'
import { cohortCountWarningLogic } from './cohortCountWarningLogic'
import { createCohortDataNodeLogicKey } from './cohortUtils'

const RESOURCE_TYPE = 'cohort'

export interface CohortEditProps {
    id?: CohortType['id']
    attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>
    tabId: string
}

export function CohortEdit({ id, attachTo, tabId }: CohortEditProps): JSX.Element {
    const logicProps = { id, tabId }

    const renderRemovePersonFromCohortButton = ({ record }: { record: unknown }): JSX.Element => {
        if (!Array.isArray(record)) {
            console.error('Expected record to be an array for person.$delete column')
            return <></>
        }
        const personRecord = record[0] as PersonDisplayNameType

        return <RemovePersonFromCohortButton person={personRecord} />
    }

    const logic = cohortEditLogic(logicProps)
    useAttachedLogic(logic, attachTo)
    const {
        deleteCohort,
        restoreCohort,
        setOuterGroupsType,
        setQuery,
        duplicateCohort,
        setCohortValue,
        addPersonToCreateStaticCohort,
        removePersonFromCreateStaticCohort,
        setCreationPersonQuery,
    } = useActions(logic)
    const modalLogic = addPersonToCohortModalLogic(logicProps)
    const { showAddPersonToCohortModal } = useActions(modalLogic)
    const {
        cohort,
        cohortLoading,
        cohortMissing,
        query,
        creationPersonQuery,
        personsToCreateStaticCohort,
        canRemovePersonFromCohort,
    } = useValues(logic)
    const { featureFlags } = useValues(featureFlagLogic)

    const isNewCohort = cohort.id === 'new' || cohort.id === undefined
    const dataNodeLogicKey = createCohortDataNodeLogicKey(cohort.id)
    const warningLogic = cohortCountWarningLogic({ cohort, query, dataNodeLogicKey })
    const { shouldShowCountWarning } = useValues(warningLogic)

    const cohortId = typeof cohort.id === 'number' ? cohort.id : null

    useFileSystemLogView({
        type: 'cohort',
        ref: cohortId,
        enabled: Boolean(cohortId && !cohortLoading && !cohortMissing && !cohort.deleted),
        deps: [cohortId, cohortLoading, cohortMissing, cohort.deleted],
    })

    const createStaticCohortContext: QueryContext = {
        columns: {
            id: {
                renderTitle: () => null,
                render: (props) => {
                    const id = props.value as string
                    const isAdded = personsToCreateStaticCohort[id] != null
                    return (
                        <LemonButton
                            type="secondary"
                            status={isAdded ? 'danger' : 'default'}
                            size="small"
                            onClick={(e) => {
                                e.preventDefault()
                                if (isAdded) {
                                    removePersonFromCreateStaticCohort(id)
                                } else {
                                    addPersonToCreateStaticCohort(id)
                                }
                            }}
                        >
                            {isAdded ? <IconMinusSmall /> : <IconPlusSmall />}
                        </LemonButton>
                    )
                },
            },
        },
        showOpenEditorButton: false,
    }

    if (cohortMissing) {
        return <NotFound object="cohort" />
    }

    if (cohort.deleted) {
        return (
            <div>
                <LemonBanner type="error">The cohort '{cohort.name}' has been soft deleted.</LemonBanner>
                <ScenePanel>
                    <ButtonPrimitive
                        disabled={cohortLoading}
                        onClick={() => {
                            restoreCohort()
                        }}
                        menuItem
                    >
                        <IconRefresh /> Restore
                    </ButtonPrimitive>
                </ScenePanel>
            </div>
        )
    }

    return (
        <BindLogic logic={cohortEditLogic} props={logicProps}>
            <div className="cohort">
                <AddPersonToCohortModal id={id} tabId={tabId} />

                <ScenePanel>
                    <ScenePanelInfoSection>
                        <SceneFile dataAttrKey={RESOURCE_TYPE} />
                    </ScenePanelInfoSection>

                    <ScenePanelDivider />

                    <ScenePanelActionsSection>
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
                                'Cohort must be dynamic to duplicate': cohort.is_static === true,
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
                                'Cohort is still calculating': cohort.is_calculating ?? false,
                            }}
                            menuItem
                        >
                            <IconCopy /> Duplicate as static cohort
                        </ButtonPrimitive>

                        {!cohort.is_static && featureFlags[FEATURE_FLAGS.COHORT_CALCULATION_HISTORY] && (
                            <ButtonPrimitive
                                onClick={() => router.actions.push(urls.cohortCalculationHistory(cohort.id))}
                                disabledReasons={{
                                    'Save the cohort first': isNewCohort,
                                }}
                                menuItem
                            >
                                <IconClock /> Calculation history
                            </ButtonPrimitive>
                        )}
                    </ScenePanelActionsSection>
                    {!isNewCohort && (
                        <>
                            <ScenePanelDivider />
                            <ScenePanelActionsSection>
                                <ButtonPrimitive
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Delete cohort?',
                                            description: `Are you sure you want to delete "${cohort.name}"?`,
                                            primaryButton: {
                                                children: 'Delete',
                                                status: 'danger',
                                                onClick: () => deleteCohort(),
                                                size: 'small',
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                                type: 'tertiary',
                                                size: 'small',
                                            },
                                        })
                                    }}
                                    variant="danger"
                                    menuItem
                                    data-attr={`${RESOURCE_TYPE}-delete`}
                                >
                                    <IconTrash />
                                    Delete
                                </ButtonPrimitive>
                            </ScenePanelActionsSection>
                        </>
                    )}
                </ScenePanel>

                <Form id="cohort" logic={cohortEditLogic} props={logicProps} formKey="cohort" enableFormOnSubmit>
                    <SceneContent>
                        <LemonField name="name">
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
                                canEdit
                                forceEdit={isNewCohort}
                                actions={
                                    <>
                                        {isNewCohort ? (
                                            <LemonButton
                                                data-attr="cancel-cohort"
                                                type="secondary"
                                                onClick={() => {
                                                    router.actions.push(urls.cohorts())
                                                }}
                                                size="small"
                                                disabled={cohortLoading}
                                            >
                                                Cancel
                                            </LemonButton>
                                        ) : null}
                                        <LemonButton
                                            type="primary"
                                            data-attr="save-cohort"
                                            htmlType="submit"
                                            loading={cohortLoading || cohort.is_calculating}
                                            form="cohort"
                                            size="small"
                                        >
                                            Save
                                        </LemonButton>
                                    </>
                                }
                            />
                        </LemonField>

                        <SceneDivider />

                        <SceneSection
                            title="Type"
                            description="Static cohorts are created once and never updated, while dynamic cohorts are recalculated based on the latest data."
                            className="max-w-200 flex flex-col gap-y-2"
                            hideTitleAndDescription
                        >
                            <div className="flex gap-4 flex-wrap">
                                <div className={cn('flex-1 flex flex-col gap-y-4')}>
                                    <LemonField name="is_static" label={null}>
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

                                    {!isNewCohort && !cohort?.is_static && (
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
                            </div>
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
                                        files, include a header row with a 'person_id', 'distinct_id', or 'email' column
                                        containing the user identifiers.`
                                            : undefined
                                    }
                                    className={cn('ph-ignore-input')}
                                >
                                    {!isNewCohort && (
                                        <div className="flex flex-col gap-y-0 flex-1 justify-center">
                                            <h3 className="text-sm">Upload a CSV</h3>
                                            <span className="max-w-prose">
                                                Upload a CSV file to add users to your cohort. For single-column files,
                                                include one distinct ID per row (all rows will be processed as data).
                                                For multi-column files, include a header row with a 'person_id',
                                                'distinct_id', or 'email' column containing the user identifiers.
                                            </span>
                                        </div>
                                    )}
                                    {/* TODO: @adamleithp Allow users to download a template CSV file */}
                                    {/* TODO: @adamleithp Tell users that adding ANOTHER file will NOT(?) replace the current one */}
                                    {/* TODO: @adamleithp Render the csv file and validate it */}
                                    {/* TODO: @adamleithp Adding a csv file doesn't show up with cohort.csv... */}
                                    <LemonField name="csv" data-attr="cohort-csv">
                                        {({ onChange }) => (
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
                                                            'text-primary mt-0 bg-transparent border border-dashed border-primary hover:border-secondary p-8',
                                                            cohort.csv?.name && 'border-success'
                                                        )}
                                                    >
                                                        {cohort.csv ? (
                                                            <>
                                                                <IconUploadFile
                                                                    style={{
                                                                        fontSize: '3rem',
                                                                        color: 'var(--color-text-primary)',
                                                                    }}
                                                                />
                                                                <div>{cohort.csv?.name ?? 'File chosen'}</div>
                                                            </>
                                                        ) : (
                                                            <>
                                                                <IconUploadFile
                                                                    style={{
                                                                        fontSize: '3rem',
                                                                        color: 'var(--color-text-primary)',
                                                                    }}
                                                                />
                                                                <div>
                                                                    Drag a file here or click to browse for a file
                                                                </div>
                                                                <div className="text-secondary text-xs">
                                                                    Accepts .csv files only
                                                                </div>
                                                            </>
                                                        )}
                                                    </div>
                                                }
                                            />
                                        )}
                                    </LemonField>
                                </SceneSection>
                                {isNewCohort && (
                                    <>
                                        <LemonDivider label="OR" />
                                        <div>
                                            <h3 className="font-semibold my-0 mb-1 max-w-prose">Add users manually</h3>
                                            <span className="max-w-prose">
                                                Select the users that you would like to add to the new cohort.
                                            </span>
                                        </div>
                                        <Query
                                            query={creationPersonQuery}
                                            setQuery={setCreationPersonQuery}
                                            context={createStaticCohortContext}
                                        />
                                    </>
                                )}
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
                                <SceneDivider />
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
                                    <AndOrFilterSelect
                                        value={cohort.filters.properties.type}
                                        onChange={(value) => {
                                            setOuterGroupsType(value)
                                        }}
                                        topLevelFilter={true}
                                        suffix={['criterion', 'criteria']}
                                    />
                                    <div className={cn('w-full [&>div]:my-0 [&>div]:w-full')}>
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
                                                    cohort.count != undefined &&
                                                    `(${cohort.count})`}
                                            </span>
                                            {shouldShowCountWarning && (
                                                <Tooltip title="The displayed number of persons is less than the cohort count due to deleted persons. This is expected behavior for dynamic cohorts where persons may be deleted after being counted.">
                                                    <IconWarning className="text-warning ml-2" />
                                                </Tooltip>
                                            )}
                                        </>
                                    }
                                    description="Persons who match the following criteria will be part of the cohort."
                                    hideTitleAndDescription
                                >
                                    <div>
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
                                                    columns: canRemovePersonFromCohort
                                                        ? {
                                                              'person.$delete': {
                                                                  render: renderRemovePersonFromCohortButton,
                                                              },
                                                          }
                                                        : undefined,
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
        </BindLogic>
    )
}
