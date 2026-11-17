import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IconArchive,
    IconCopy,
    IconDashboard,
    IconExternal,
    IconFlask,
    IconLock,
    IconMessage,
    IconPause,
    IconPeople,
    IconPlay,
    IconPlusSmall,
    IconRefresh,
    IconRocket,
    IconTrash,
    IconUnlock,
} from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
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
} from 'products/experiments/frontend/experimentActions'
import { isExperimentExposureFrozen, isExperimentPaused } from 'products/experiments/frontend/experimentStatus'
import { getTotalExposures } from 'products/experiments/frontend/health/exposureHealth'
import { experimentUsesWarehouseNativeSources } from 'products/experiments/frontend/warehouseNative/warehouseNativeSources'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { isLegacyExperiment } from '../utils'
import { FinishExperimentModal } from './ExperimentModals'

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
        isExperimentDraft,
        isExperimentRunning,
        isExperimentLaunched,
        isExperimentStopped,
        isCreatingExperimentDashboard,
        exposures,
        freezeExposureLoading,
        unfreezeExposureLoading,
        showDebugPanel,
        launchExperimentLoading,
    } = useValues(experimentLogic)
    const {
        archiveExperiment,
        unarchiveExperiment,
        createExposureCohort,
        createExperimentDashboard,
        resetRunningExperiment,
        toggleDebugPanel,
        launchExperiment,
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
        openFinishExperimentModal,
    } = useActions(modalsLogic)
    const { superpowersEnabled } = useValues(superpowersLogic)
    const fileActions = useSceneFileActions(RESOURCE_TYPE, { section: 'project' })

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
    const canEnd = isExperimentRunning && !isExperimentStopped
    const launchDisabledReason = experimentUsesWarehouseNativeSources(experiment)
        ? 'Warehouse-native experiments cannot run yet. You can keep this one as a draft.'
        : undefined
    const endTooltip = 'Conclude this experiment and decide which variant to keep'

    const handleArchive = (): void =>
        confirmArchiveExperiment(experiment, (disableFlag) => archiveExperiment(disableFlag))
    const handleDelete = (): void =>
        confirmDeleteExperiment({
            projectId: currentProjectId,
            experiment,
            onDelete: () => router.actions.push(urls.experiments()),
        })
    const handleReset = (): void => confirmResetExperiment(experiment, resetRunningExperiment)

    const actions: SceneAction[] = [
        ...(isExperimentLaunched
            ? ([
                  {
                      group: 'file',
                      section: 'create',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-create`,
                      label: 'Create',
                      icon: <IconPlusSmall />,
                      items: [
                          exposureCohortId
                              ? {
                                    id: `${RESOURCE_TYPE}-menubar-view-exposure-cohort`,
                                    label: 'View exposure cohort',
                                    icon: <IconPeople />,
                                    shortcut: <IconExternal />,
                                    onSelect: () => newInternalTab(urls.cohort(exposureCohortId)),
                                }
                              : {
                                    id: `${RESOURCE_TYPE}-menubar-create-exposure-cohort`,
                                    label: 'Exposure cohort',
                                    icon: <IconPeople />,
                                    onSelect: () => createExposureCohort(),
                                },
                          {
                              id: `${RESOURCE_TYPE}-menubar-create-dashboard`,
                              label: 'Dashboard',
                              icon: <IconDashboard />,
                              disabledReason: isCreatingExperimentDashboard ? 'Creating dashboard…' : undefined,
                              onSelect: () => createExperimentDashboard(),
                          },
                          ...(experiment.feature_flag
                              ? [
                                    {
                                        id: `${RESOURCE_TYPE}-menubar-create-survey`,
                                        label: 'Survey',
                                        icon: <IconMessage />,
                                        opensFloatingUi: true,
                                        onSelect: () => {
                                            openQuickSurveyModal()
                                            void addProductIntentForCrossSell({
                                                from: ProductKey.EXPERIMENTS,
                                                to: ProductKey.SURVEYS,
                                                intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
                                            })
                                        },
                                    },
                                ]
                              : []),
                      ],
                  },
              ] satisfies SceneAction[])
            : []),
        ...fileActions,
        ...(hasMultipleProjects
            ? ([
                  {
                      group: 'file',
                      section: 'project',
                      id: `${RESOURCE_TYPE}-menubar-copy-to-project`,
                      label: 'Copy to another project',
                      icon: <IconCopy />,
                      opensFloatingUi: true,
                      disabledReason: isLegacyExperiment(experiment)
                          ? 'Copying is not supported for experiments using legacy metrics.'
                          : undefined,
                      onSelect: () => openCopyToProjectModal(),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canEdit && experiment.archived
            ? ([
                  {
                      group: 'file',
                      section: 'archive',
                      id: `${RESOURCE_TYPE}-menubar-unarchive`,
                      label: 'Unarchive experiment',
                      icon: <IconArchive />,
                      onSelect: () => unarchiveExperiment(),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canArchive
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-archive`,
                      label: 'Archive experiment',
                      icon: <IconArchive />,
                      destructive: true,
                      onSelect: handleArchive,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canDelete
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-delete`,
                      label: 'Delete experiment',
                      icon: <IconTrash />,
                      destructive: true,
                      onSelect: handleDelete,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(isExperimentDraft
            ? ([
                  {
                      group: 'edit',
                      section: 'lifecycle',
                      id: `${RESOURCE_TYPE}-menubar-launch`,
                      label: 'Launch',
                      icon: <IconRocket />,
                      disabledReason: launchDisabledReason ?? (launchExperimentLoading ? 'Launching…' : undefined),
                      onSelect: () => launchExperiment(),
                      pinned: {
                          order: 1,
                          variant: 'primary',
                          render: () => (
                              <Button
                                  variant="primary"
                                  data-attr="launch-experiment"
                                  onClick={() => launchExperiment()}
                                  loading={launchExperimentLoading}
                                  disabledReason={launchDisabledReason}
                              >
                                  Launch
                              </Button>
                          ),
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canEnd
            ? ([
                  {
                      group: 'edit',
                      section: 'lifecycle',
                      id: `${RESOURCE_TYPE}-menubar-end`,
                      label: 'End experiment',
                      icon: <IconFlask />,
                      tooltip: endTooltip,
                      opensFloatingUi: true,
                      onSelect: () => openFinishExperimentModal(),
                      pinned: {
                          order: 1,
                          variant: 'primary',
                          // The title row's own button mounts the modal, and the pinned row replaces it.
                          render: () => (
                              <>
                                  <Button
                                      variant="primary"
                                      tooltip={endTooltip}
                                      onClick={() => openFinishExperimentModal()}
                                  >
                                      <IconFlask />
                                      <b>End experiment</b>
                                  </Button>
                                  <FinishExperimentModal />
                              </>
                          ),
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showRunningState && paused
            ? ([
                  {
                      group: 'edit',
                      section: 'lifecycle',
                      id: `${RESOURCE_TYPE}-menubar-resume`,
                      label: 'Resume experiment',
                      icon: <IconPlay />,
                      opensFloatingUi: true,
                      onSelect: () => openResumeExperimentModal(),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showRunningState && !paused && showFreezeExposure
            ? ([
                  {
                      group: 'edit',
                      section: 'lifecycle',
                      id: `${RESOURCE_TYPE}-menubar-freeze-exposure`,
                      label: 'Freeze exposure',
                      icon: <IconLock />,
                      opensFloatingUi: true,
                      disabledReason: freezeExposureLoading ? 'Freezing exposure…' : undefined,
                      onSelect: () => confirmFreezeExposure(() => freezeExposure(), getTotalExposures(exposures)),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showRunningState && !paused && isExperimentExposureFrozen(experiment)
            ? ([
                  {
                      group: 'edit',
                      section: 'lifecycle',
                      id: `${RESOURCE_TYPE}-menubar-unfreeze-exposure`,
                      label: 'Unfreeze exposure',
                      icon: <IconUnlock />,
                      opensFloatingUi: true,
                      disabledReason: unfreezeExposureLoading ? 'Unfreezing exposure…' : undefined,
                      onSelect: () => confirmUnfreezeExposure(() => unfreezeExposure()),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'edit',
            section: 'copy',
            id: `${RESOURCE_TYPE}-menubar-duplicate`,
            label: 'Duplicate',
            icon: <IconCopy />,
            opensFloatingUi: true,
            onSelect: () => openDuplicateExperimentModal(),
        },
        ...(isExperimentLaunched
            ? ([
                  {
                      group: 'edit',
                      section: 'copy',
                      id: `${RESOURCE_TYPE}-menubar-reset`,
                      label: 'Reset analysis',
                      icon: <IconRefresh />,
                      opensFloatingUi: true,
                      onSelect: handleReset,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showRunningState && !paused
            ? ([
                  {
                      group: 'edit',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-pause`,
                      label: 'Pause experiment',
                      icon: <IconPause />,
                      destructive: true,
                      opensFloatingUi: true,
                      onSelect: () => openPauseExperimentModal(),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(superpowersEnabled
            ? ([
                  {
                      group: 'staff',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-debug-panel`,
                      label: 'Show debug panel',
                      checked: showDebugPanel,
                      onCheckedChange: () => toggleDebugPanel(),
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
