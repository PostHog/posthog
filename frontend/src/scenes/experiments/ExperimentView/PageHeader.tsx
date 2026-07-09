import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import {
    IconArchive,
    IconCopy,
    IconEye,
    IconFlask,
    IconLock,
    IconPause,
    IconPlay,
    IconPlusSmall,
    IconRefresh,
    IconTrash,
} from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { CopyExperimentToProjectModal } from '../CopyExperimentToProjectModal'
import { DuplicateExperimentModal } from '../DuplicateExperimentModal'
import {
    canArchiveExperiment,
    canFreezeExposure,
    confirmArchiveExperiment,
    confirmDeleteExperiment,
    confirmFreezeExposure,
    hasFrozenExposureStamps,
} from '../experimentActions'
import { experimentLogic } from '../experimentLogic'
import { isExperimentPaused } from '../experimentsLogic'
import { modalsLogic } from '../modalsLogic'
import { isLegacyExperiment } from '../utils'
import { FinishExperimentModal, PauseExperimentModal, ResumeExperimentModal } from './ExperimentModals'
import { ExperimentSceneMenuBar } from './ExperimentSceneMenuBar'

export function PageHeaderCustom(): JSX.Element {
    const {
        experiment,
        isExperimentDraft,
        isExperimentRunning,
        isExperimentLaunched,
        isExperimentStopped,
        isCreatingExperimentDashboard,
        experimentLoading,
        launchExperimentLoading,
        freezeExposureLoading,
    } = useValues(experimentLogic)
    const {
        launchExperiment,
        archiveExperiment,
        unarchiveExperiment,
        createExposureCohort,
        createExperimentDashboard,
        updateExperiment,
        setHogfettiTrigger,
        freezeExposure,
    } = useActions(experimentLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const hasMultipleProjects = (currentOrganization?.projects?.length ?? 0) > 1
    const { openFinishExperimentModal, openPauseExperimentModal, openResumeExperimentModal } = useActions(modalsLogic)
    const [duplicateModalOpen, setDuplicateModalOpen] = useState(false)
    const [copyToProjectModalOpen, setCopyToProjectModalOpen] = useState(false)
    const [surveyModalOpen, setSurveyModalOpen] = useState(false)
    const { trigger, HogfettiComponent } = useHogfetti()

    useOnMountEffect(() => {
        setHogfettiTrigger(trigger)
    })

    const exposureCohortId = experiment?.exposure_cohort

    const canEdit = userHasAccess(
        AccessControlResourceType.Experiment,
        AccessControlLevel.Editor,
        experiment.user_access_level
    )
    const canArchive = canEdit && canArchiveExperiment(experiment)
    const canDelete = canEdit

    const handleArchive = (): void =>
        confirmArchiveExperiment(experiment, (disableFlag) => archiveExperiment(disableFlag))
    const handleDelete = (): void =>
        confirmDeleteExperiment({
            projectId: currentProjectId,
            experiment,
            onDelete: () => router.actions.push(urls.experiments()),
        })

    return (
        <>
            <ExperimentSceneMenuBar />
            <SceneTitleSection
                name={experiment?.name}
                description={null}
                resourceType={{
                    type: 'experiment',
                }}
                isLoading={experimentLoading}
                onNameChange={(name) => updateExperiment({ name })}
                onDescriptionChange={(description) => updateExperiment({ description })}
                canEdit={canEdit}
                renameDebounceMs={0}
                saveOnBlur
                actions={
                    <>
                        {experiment && isExperimentDraft && (
                            <div className="flex items-center">
                                <LemonButton
                                    type="primary"
                                    data-attr="launch-experiment"
                                    onClick={() => launchExperiment()}
                                    loading={launchExperimentLoading}
                                    size="small"
                                >
                                    Launch
                                </LemonButton>
                            </div>
                        )}
                        {canArchive && (
                            <LemonButton type="secondary" status="danger" onClick={handleArchive} size="small">
                                <b>Archive</b>
                            </LemonButton>
                        )}
                        {experiment && isExperimentRunning && !isExperimentStopped && (
                            <>
                                <Tooltip title="Conclude this experiment and decide which variant to keep">
                                    <LemonButton
                                        type="primary"
                                        icon={<IconFlask />}
                                        onClick={() => openFinishExperimentModal()}
                                        size="small"
                                    >
                                        <b>End experiment</b>
                                    </LemonButton>
                                </Tooltip>
                                <FinishExperimentModal />
                            </>
                        )}
                        {experiment && (
                            <DuplicateExperimentModal
                                isOpen={duplicateModalOpen}
                                onClose={() => setDuplicateModalOpen(false)}
                                experiment={experiment}
                            />
                        )}
                        {experiment && (
                            <CopyExperimentToProjectModal
                                isOpen={copyToProjectModalOpen}
                                onClose={() => setCopyToProjectModalOpen(false)}
                                experiment={experiment}
                            />
                        )}
                    </>
                }
            />
            <HogfettiComponent />

            {experiment && (
                <ScenePanel>
                    <ScenePanelActionsSection>
                        <ButtonPrimitive menuItem onClick={() => setDuplicateModalOpen(true)}>
                            <IconCopy />
                            Duplicate
                        </ButtonPrimitive>

                        {hasMultipleProjects && (
                            <ButtonPrimitive
                                menuItem
                                onClick={() => setCopyToProjectModalOpen(true)}
                                disabledReasons={{
                                    'Copying is not supported for experiments using legacy metrics.':
                                        isLegacyExperiment(experiment),
                                }}
                            >
                                <IconCopy />
                                Copy to project
                            </ButtonPrimitive>
                        )}

                        {isExperimentLaunched && (
                            <>
                                {exposureCohortId ? (
                                    // TODO: add custom back button to the destination page
                                    <Link
                                        to={urls.cohort(exposureCohortId)}
                                        buttonProps={{
                                            menuItem: true,
                                        }}
                                        data-attr="view-exposure-cohort"
                                        onClick={() => newInternalTab(urls.cohort(exposureCohortId))}
                                    >
                                        <IconEye /> View exposure cohort as new tab
                                    </Link>
                                ) : (
                                    <ButtonPrimitive
                                        menuItem
                                        onClick={() => createExposureCohort()}
                                        data-attr="create-exposure-cohort"
                                    >
                                        <IconPlusSmall /> Create exposure cohort
                                    </ButtonPrimitive>
                                )}
                                <ButtonPrimitive
                                    menuItem
                                    onClick={() => createExperimentDashboard()}
                                    disabledReasons={{
                                        'Creating dashboard...': isCreatingExperimentDashboard,
                                    }}
                                >
                                    <IconPlusSmall /> Create dashboard
                                </ButtonPrimitive>

                                {experiment.feature_flag && (
                                    <ButtonPrimitive
                                        menuItem
                                        onClick={() => {
                                            setSurveyModalOpen(true)
                                            void addProductIntentForCrossSell({
                                                from: ProductKey.EXPERIMENTS,
                                                to: ProductKey.SURVEYS,
                                                intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
                                            })
                                        }}
                                    >
                                        <IconPlusSmall /> Create survey
                                    </ButtonPrimitive>
                                )}

                                <LemonDivider />

                                {isExperimentRunning &&
                                    experiment.feature_flag &&
                                    (isExperimentPaused(experiment) ? (
                                        <ButtonPrimitive
                                            menuItem
                                            data-attr="resume-experiment"
                                            onClick={() => openResumeExperimentModal()}
                                        >
                                            <IconPlay /> Resume experiment
                                        </ButtonPrimitive>
                                    ) : (
                                        <>
                                            {canFreezeExposure(experiment) && (
                                                <ButtonPrimitive
                                                    menuItem
                                                    data-attr="freeze-exposure"
                                                    onClick={() => confirmFreezeExposure(freezeExposure)}
                                                    disabledReasons={{
                                                        'Freezing exposure...': freezeExposureLoading,
                                                    }}
                                                >
                                                    <IconLock /> Freeze exposure
                                                </ButtonPrimitive>
                                            )}
                                            <ButtonPrimitive
                                                variant="danger"
                                                menuItem
                                                data-attr="pause-experiment"
                                                onClick={() => openPauseExperimentModal()}
                                            >
                                                <IconPause /> Pause experiment
                                            </ButtonPrimitive>
                                        </>
                                    ))}

                                <ResetButton />
                            </>
                        )}

                        <LemonDivider />

                        {canArchive && (
                            <ButtonPrimitive menuItem data-attr="archive-experiment" onClick={handleArchive}>
                                <IconArchive /> Archive experiment
                            </ButtonPrimitive>
                        )}
                        {canEdit && experiment.archived && (
                            <ButtonPrimitive
                                menuItem
                                data-attr="unarchive-experiment"
                                onClick={() => unarchiveExperiment()}
                            >
                                <IconArchive /> Unarchive experiment
                            </ButtonPrimitive>
                        )}

                        {canDelete && (
                            <ButtonPrimitive
                                variant="danger"
                                menuItem
                                data-attr="delete-experiment"
                                onClick={handleDelete}
                            >
                                <IconTrash /> Delete experiment
                            </ButtonPrimitive>
                        )}

                        <PauseExperimentModal />
                        <ResumeExperimentModal />
                    </ScenePanelActionsSection>
                    <ExperimentDebugToggle />
                </ScenePanel>
            )}
            <QuickSurveyModal
                context={{ type: QuickSurveyType.EXPERIMENT, experiment }}
                isOpen={surveyModalOpen}
                onCancel={() => setSurveyModalOpen(false)}
            />
        </>
    )
}

function ExperimentDebugToggle(): JSX.Element {
    const { superpowersEnabled } = useValues(superpowersLogic)
    const { showDebugPanel } = useValues(experimentLogic)
    const { toggleDebugPanel } = useActions(experimentLogic)

    if (!superpowersEnabled) {
        return <></>
    }

    return (
        <ScenePanelActionsSection>
            <LemonSwitch
                className="px-2 py-1"
                checked={showDebugPanel}
                onChange={toggleDebugPanel}
                fullWidth
                label="Debug panel"
            />
        </ScenePanelActionsSection>
    )
}

const ResetButton = (): JSX.Element => {
    const { experiment } = useValues(experimentLogic)
    const { resetRunningExperiment } = useActions(experimentLogic)

    const onClickReset = (): void => {
        LemonDialog.open({
            title: 'Reset analysis?',
            content: (
                <>
                    <div className="text-sm text-secondary max-w-md">
                        <p>
                            The experiment start and end dates will be reset and the experiment will go back to draft
                            mode.
                        </p>
                        <p>
                            All events collected thus far will still exist, but won't be applied to the experiment
                            unless you manually change the start date after launching the experiment again.
                        </p>
                        {hasFrozenExposureStamps(experiment) ? (
                            <p>
                                The <b>exposure freeze is removed</b>: the flag serves its original release conditions
                                again and the snapshot cohort is deleted. Everything else on the flag stays untouched.
                            </p>
                        ) : (
                            <p>
                                The <b>feature flag remains untouched</b>, so variants stay visible to users.
                            </p>
                        )}
                    </div>
                    {experiment.archived && (
                        <div className="text-sm text-secondary">Resetting will also unarchive the experiment.</div>
                    )}
                </>
            ),
            primaryButton: {
                children: 'Confirm',
                type: 'primary',
                onClick: resetRunningExperiment,
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    return (
        <ButtonPrimitive variant="danger" menuItem onClick={onClickReset} data-attr="reset-experiment">
            <IconRefresh /> Reset analysis
        </ButtonPrimitive>
    )
}
