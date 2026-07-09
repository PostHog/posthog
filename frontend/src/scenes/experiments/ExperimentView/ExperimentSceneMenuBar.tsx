import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import {
    IconArchive,
    IconCopy,
    IconEye,
    IconLock,
    IconPause,
    IconPlay,
    IconPlusSmall,
    IconRefresh,
    IconTrash,
    IconUnlock,
} from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'

import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
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

import { CopyExperimentToProjectModal } from '../CopyExperimentToProjectModal'
import { DuplicateExperimentModal } from '../DuplicateExperimentModal'
import {
    canArchiveExperiment,
    canFreezeExposure,
    confirmArchiveExperiment,
    confirmDeleteExperiment,
    confirmFreezeExposure,
    confirmUnfreezeExposure,
    hasFrozenExposureStamps,
} from '../experimentActions'
import { experimentLogic } from '../experimentLogic'
import { isExperimentExposureFrozen, isExperimentPaused } from '../experimentsLogic'
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
        freezeExposure,
        unfreezeExposure,
        toggleDebugPanel,
    } = useActions(experimentLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { openPauseExperimentModal, openResumeExperimentModal } = useActions(modalsLogic)
    const { superpowersEnabled } = useValues(superpowersLogic)

    const [duplicateModalOpen, setDuplicateModalOpen] = useState(false)
    const [copyToProjectModalOpen, setCopyToProjectModalOpen] = useState(false)
    const [surveyModalOpen, setSurveyModalOpen] = useState(false)

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

    const handleReset = (): void => {
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

    const showCreateMenu = isExperimentLaunched
    const showStateMenu = showRunningState
    const showStaffMenu = superpowersEnabled

    return (
        <>
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
                                        <IconEye />
                                        View exposure cohort as new tab
                                    </SceneMenuBarItem>
                                ) : (
                                    <SceneMenuBarItem
                                        onClick={() => createExposureCohort()}
                                        data-attr={`${RESOURCE_TYPE}-menubar-create-exposure-cohort`}
                                    >
                                        <IconPlusSmall />
                                        Exposure cohort
                                    </SceneMenuBarItem>
                                )}
                                <SceneMenuBarItem
                                    onClick={() => createExperimentDashboard()}
                                    disabled={isCreatingExperimentDashboard}
                                    data-attr={`${RESOURCE_TYPE}-menubar-create-dashboard`}
                                >
                                    <IconPlusSmall />
                                    Dashboard
                                </SceneMenuBarItem>
                                {experiment.feature_flag && (
                                    <SceneMenuBarItem
                                        opensFloatingUi
                                        onClick={() => {
                                            setSurveyModalOpen(true)
                                            void addProductIntentForCrossSell({
                                                from: ProductKey.EXPERIMENTS,
                                                to: ProductKey.SURVEYS,
                                                intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
                                            })
                                        }}
                                        data-attr={`${RESOURCE_TYPE}-menubar-create-survey`}
                                    >
                                        <IconPlusSmall />
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
                            onClick={() => setCopyToProjectModalOpen(true)}
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
                        onClick={() => setDuplicateModalOpen(true)}
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
                                        onClick={() => confirmFreezeExposure(freezeExposure)}
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
                                        onClick={() => confirmUnfreezeExposure(unfreezeExposure)}
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
            <DuplicateExperimentModal
                isOpen={duplicateModalOpen}
                onClose={() => setDuplicateModalOpen(false)}
                experiment={experiment}
            />
            <CopyExperimentToProjectModal
                isOpen={copyToProjectModalOpen}
                onClose={() => setCopyToProjectModalOpen(false)}
                experiment={experiment}
            />
            <QuickSurveyModal
                context={{ type: QuickSurveyType.EXPERIMENT, experiment }}
                isOpen={surveyModalOpen}
                onCancel={() => setSurveyModalOpen(false)}
            />
        </>
    )
}
