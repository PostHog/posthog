import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IconArchive,
    IconCopy,
    IconDashboard,
    IconExternal,
    IconLock,
    IconMessage,
    IconPause,
    IconPeople,
    IconPlay,
    IconRefresh,
    IconTrash,
    IconUnlock,
} from '@posthog/icons'

import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { isExperimentExposureFrozen, isExperimentPaused } from 'scenes/experiments/experimentStatus'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import {
    SceneMenuBar,
    SceneMenuBarCheckboxItem,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from '~/layout/scenes/components/SceneMenuBar'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import {
    canArchiveExperiment,
    canFreezeExposure,
    confirmArchiveExperiment,
    confirmDeleteExperiment,
    confirmFreezeExposure,
    confirmResetExperiment,
    confirmUnfreezeExposure,
} from '../experimentActions'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { isLegacyExperiment } from '../utils'

const RESOURCE_TYPE = 'experiment'

export function ExperimentSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <ExperimentSceneMenuBarInner />
}

function ExperimentSceneMenuBarInner(): JSX.Element | null {
    const {
        experiment,
        isExperimentRunning,
        isExperimentLaunched,
        isExperimentStopped,
        isCreatingExperimentDashboard,
        freezeExposureLoading,
        unfreezeExposureLoading,
        showDebugPanel,
    } = useValues(experimentLogic)
    const {
        archiveExperiment,
        unarchiveExperiment,
        createExposureCohort,
        createExperimentDashboard,
        resetRunningExperiment,
        toggleDebugPanel,
    } = useActions(experimentLogic)
    // Promise-returning dispatch so the confirm dialogs can await completion (shouldAwaitSubmit).
    const { freezeExposure, unfreezeExposure } = useAsyncActions(experimentLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const {
        openPauseExperimentModal,
        openResumeExperimentModal,
        openDuplicateExperimentModal,
        openCopyToProjectModal,
        openQuickSurveyModal,
    } = useActions(modalsLogic)
    const { superpowersEnabled } = useValues(superpowersLogic)

    if (!experiment) {
        return null
    }

    const hasMultipleProjects = (currentOrganization?.projects?.length ?? 0) > 1
    const canEdit = userHasAccess(
        AccessControlResourceType.Experiment,
        AccessControlLevel.Editor,
        experiment.user_access_level
    )
    const canArchive = canEdit && canArchiveExperiment(experiment)
    const canDelete = canEdit
    const exposureCohortId = experiment?.exposure_cohort
    const showRunningState = isExperimentRunning && !isExperimentStopped && !!experiment.feature_flag
    const paused = isExperimentPaused(experiment)
    const showFreezeExposure = canFreezeExposure(experiment)

    const handleArchive = (): void =>
        confirmArchiveExperiment(experiment, (disableFlag) => archiveExperiment(disableFlag))
    const handleDelete = (): void =>
        confirmDeleteExperiment({
            projectId: currentProjectId,
            experiment,
            onDelete: () => router.actions.push(urls.experiments()),
        })

    const handleReset = (): void => confirmResetExperiment(experiment, resetRunningExperiment)

    const showCreateMenu = isExperimentLaunched
    const showStateMenu = showRunningState
    const showStaffMenu = superpowersEnabled

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                {showCreateMenu && (
                    <>
                        <SceneMenuBarSubMenu label="Create">
                            {exposureCohortId ? (
                                <SceneMenuBarItem
                                    onClick={() => newInternalTab(urls.cohort(exposureCohortId))}
                                    data-attr={`${RESOURCE_TYPE}-menubar-view-exposure-cohort`}
                                >
                                    <IconPeople />
                                    View exposure cohort
                                    <IconExternal />
                                </SceneMenuBarItem>
                            ) : (
                                <SceneMenuBarItem
                                    onClick={() => createExposureCohort()}
                                    data-attr={`${RESOURCE_TYPE}-menubar-create-exposure-cohort`}
                                >
                                    <IconPeople />
                                    Exposure cohort
                                </SceneMenuBarItem>
                            )}
                            <SceneMenuBarItem
                                onClick={() => createExperimentDashboard()}
                                disabled={isCreatingExperimentDashboard}
                                data-attr={`${RESOURCE_TYPE}-menubar-create-dashboard`}
                            >
                                <IconDashboard />
                                Dashboard
                            </SceneMenuBarItem>
                            {experiment.feature_flag && (
                                <SceneMenuBarItem
                                    opensFloatingUi
                                    onClick={() => {
                                        openQuickSurveyModal()
                                        void addProductIntentForCrossSell({
                                            from: ProductKey.EXPERIMENTS,
                                            to: ProductKey.SURVEYS,
                                            intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
                                        })
                                    }}
                                    data-attr={`${RESOURCE_TYPE}-menubar-create-survey`}
                                >
                                    <IconMessage />
                                    Survey
                                </SceneMenuBarItem>
                            )}
                        </SceneMenuBarSubMenu>
                        <SceneMenuBarSeparator />
                    </>
                )}
                <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                {hasMultipleProjects && (
                    <SceneMenuBarItem
                        opensFloatingUi
                        onClick={() => openCopyToProjectModal()}
                        disabled={isLegacyExperiment(experiment)}
                        tooltip={
                            isLegacyExperiment(experiment)
                                ? 'Copying is not supported for experiments using legacy metrics.'
                                : undefined
                        }
                        data-attr={`${RESOURCE_TYPE}-menubar-copy-to-project`}
                    >
                        <IconCopy />
                        Copy to another project
                    </SceneMenuBarItem>
                )}
                {(canArchive || (canEdit && experiment.archived) || canDelete) && <SceneMenuBarSeparator />}
                {canArchive && (
                    <SceneMenuBarItem
                        variant="destructive"
                        onClick={handleArchive}
                        data-attr={`${RESOURCE_TYPE}-menubar-archive`}
                    >
                        <IconArchive />
                        Archive experiment
                    </SceneMenuBarItem>
                )}
                {canEdit && experiment.archived && (
                    <SceneMenuBarItem
                        onClick={() => unarchiveExperiment()}
                        data-attr={`${RESOURCE_TYPE}-menubar-unarchive`}
                    >
                        <IconArchive />
                        Unarchive experiment
                    </SceneMenuBarItem>
                )}
                {canDelete && (
                    <SceneMenuBarItem
                        variant="destructive"
                        onClick={handleDelete}
                        data-attr={`${RESOURCE_TYPE}-menubar-delete`}
                    >
                        <IconTrash />
                        Delete experiment
                    </SceneMenuBarItem>
                )}
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="Edit" dataAttr={`${RESOURCE_TYPE}-menubar-edit`}>
                <SceneMenuBarItem
                    opensFloatingUi
                    onClick={() => openDuplicateExperimentModal()}
                    data-attr={`${RESOURCE_TYPE}-menubar-duplicate`}
                >
                    <IconCopy />
                    Duplicate
                </SceneMenuBarItem>
                {isExperimentLaunched && (
                    <SceneMenuBarItem
                        opensFloatingUi
                        onClick={handleReset}
                        data-attr={`${RESOURCE_TYPE}-menubar-reset`}
                    >
                        <IconRefresh />
                        Reset analysis
                    </SceneMenuBarItem>
                )}
                {showStateMenu &&
                    (paused ? (
                        <SceneMenuBarItem
                            opensFloatingUi
                            onClick={() => openResumeExperimentModal()}
                            data-attr={`${RESOURCE_TYPE}-menubar-resume`}
                        >
                            <IconPlay />
                            Resume experiment
                        </SceneMenuBarItem>
                    ) : (
                        <>
                            {showFreezeExposure && (
                                <SceneMenuBarItem
                                    opensFloatingUi
                                    onClick={() => confirmFreezeExposure(() => freezeExposure())}
                                    disabled={freezeExposureLoading}
                                    tooltip={freezeExposureLoading ? 'Freezing exposure…' : undefined}
                                    data-attr={`${RESOURCE_TYPE}-menubar-freeze-exposure`}
                                >
                                    <IconLock />
                                    Freeze exposure
                                </SceneMenuBarItem>
                            )}
                            {isExperimentExposureFrozen(experiment) && (
                                <SceneMenuBarItem
                                    opensFloatingUi
                                    onClick={() => confirmUnfreezeExposure(() => unfreezeExposure())}
                                    disabled={unfreezeExposureLoading}
                                    tooltip={unfreezeExposureLoading ? 'Unfreezing exposure…' : undefined}
                                    data-attr={`${RESOURCE_TYPE}-menubar-unfreeze-exposure`}
                                >
                                    <IconUnlock />
                                    Unfreeze exposure
                                </SceneMenuBarItem>
                            )}
                            <SceneMenuBarItem
                                opensFloatingUi
                                variant="destructive"
                                onClick={() => openPauseExperimentModal()}
                                data-attr={`${RESOURCE_TYPE}-menubar-pause`}
                            >
                                <IconPause />
                                Pause experiment
                            </SceneMenuBarItem>
                        </>
                    ))}
            </SceneMenuBarMenu>
            {showStaffMenu && (
                <SceneMenuBarMenu label="Staff only" dataAttr={`${RESOURCE_TYPE}-menubar-staff`}>
                    <SceneMenuBarCheckboxItem
                        checked={showDebugPanel}
                        onCheckedChange={toggleDebugPanel}
                        data-attr={`${RESOURCE_TYPE}-menubar-debug-panel`}
                    >
                        Show debug panel
                    </SceneMenuBarCheckboxItem>
                </SceneMenuBarMenu>
            )}
        </SceneMenuBar>
    )
}
