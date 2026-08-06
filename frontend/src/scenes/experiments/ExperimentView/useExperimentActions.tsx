import { useActions, useAsyncActions, useValues } from 'kea'
import { router } from 'kea-router'

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

import { LemonMenuItemLeafCallback } from 'lib/lemon-ui/LemonMenu'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

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
import { isExperimentExposureFrozen, isExperimentPaused } from '../experimentsLogic'
import { modalsLogic } from '../modalsLogic'
import { isLegacyExperiment } from '../utils'

export interface ExperimentActionsSection {
    key: string
    items: LemonMenuItemLeafCallback[]
}

/** The full action set for the current experiment, shared by the header's Actions
 * dropdown and the ScenePanel so the two surfaces can't drift apart. */
export function useExperimentActions(dataAttrPrefix: string = ''): ExperimentActionsSection[] {
    const {
        experiment,
        isExperimentLaunched,
        isExperimentRunning,
        isCreatingExperimentDashboard,
        freezeExposureLoading,
        unfreezeExposureLoading,
    } = useValues(experimentLogic)
    const {
        archiveExperiment,
        unarchiveExperiment,
        createExposureCohort,
        createExperimentDashboard,
        resetRunningExperiment,
    } = useActions(experimentLogic)
    // Promise-returning dispatch so the confirm dialogs can await completion (shouldAwaitSubmit).
    const { freezeExposure, unfreezeExposure } = useAsyncActions(experimentLogic)
    const {
        openDuplicateExperimentModal,
        openCopyToProjectModal,
        openQuickSurveyModal,
        openPauseExperimentModal,
        openResumeExperimentModal,
    } = useActions(modalsLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { currentOrganization } = useValues(organizationLogic)

    if (!experiment) {
        return []
    }

    const hasMultipleProjects = (currentOrganization?.projects?.length ?? 0) > 1
    const canEdit = userHasAccess(
        AccessControlResourceType.Experiment,
        AccessControlLevel.Editor,
        experiment.user_access_level
    )
    const canArchive = canEdit && canArchiveExperiment(experiment)
    const canDelete = canEdit
    const exposureCohortId = experiment.exposure_cohort
    const paused = isExperimentPaused(experiment)
    const showStateActions = isExperimentRunning && !!experiment.feature_flag

    const manageItems: (LemonMenuItemLeafCallback | false)[] = [
        {
            label: 'Duplicate',
            icon: <IconCopy />,
            onClick: () => openDuplicateExperimentModal(),
            'data-attr': `${dataAttrPrefix}duplicate-experiment`,
        },
        hasMultipleProjects && {
            label: 'Copy to project',
            icon: <IconCopy />,
            onClick: () => openCopyToProjectModal(),
            disabledReason: isLegacyExperiment(experiment)
                ? 'Copying is not supported for experiments using legacy metrics.'
                : undefined,
            'data-attr': `${dataAttrPrefix}copy-experiment-to-project`,
        },
        isExperimentLaunched &&
            (exposureCohortId
                ? {
                      label: 'View exposure cohort as new tab',
                      icon: <IconEye />,
                      onClick: () => newInternalTab(urls.cohort(exposureCohortId)),
                      'data-attr': `${dataAttrPrefix}view-exposure-cohort`,
                  }
                : {
                      label: 'Create exposure cohort',
                      icon: <IconPlusSmall />,
                      onClick: () => createExposureCohort(),
                      'data-attr': `${dataAttrPrefix}create-exposure-cohort`,
                  }),
        isExperimentLaunched && {
            label: 'Create dashboard',
            icon: <IconPlusSmall />,
            onClick: () => createExperimentDashboard(),
            disabledReason: isCreatingExperimentDashboard ? 'Creating dashboard...' : undefined,
            'data-attr': `${dataAttrPrefix}create-experiment-dashboard`,
        },
        isExperimentLaunched &&
            !!experiment.feature_flag && {
                label: 'Create survey',
                icon: <IconPlusSmall />,
                onClick: () => {
                    openQuickSurveyModal()
                    void addProductIntentForCrossSell({
                        from: ProductKey.EXPERIMENTS,
                        to: ProductKey.SURVEYS,
                        intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
                    })
                },
                'data-attr': `${dataAttrPrefix}create-experiment-survey`,
            },
    ]

    const stateItems: (LemonMenuItemLeafCallback | false)[] = [
        showStateActions &&
            paused && {
                label: 'Resume experiment',
                icon: <IconPlay />,
                onClick: () => openResumeExperimentModal(),
                'data-attr': `${dataAttrPrefix}resume-experiment`,
            },
        showStateActions &&
            !paused &&
            canFreezeExposure(experiment) && {
                label: 'Freeze exposure',
                icon: <IconLock />,
                onClick: () => confirmFreezeExposure(() => freezeExposure()),
                disabledReason: freezeExposureLoading ? 'Freezing exposure...' : undefined,
                'data-attr': `${dataAttrPrefix}freeze-exposure`,
            },
        showStateActions &&
            !paused &&
            isExperimentExposureFrozen(experiment) && {
                label: 'Unfreeze exposure',
                icon: <IconUnlock />,
                onClick: () => confirmUnfreezeExposure(() => unfreezeExposure()),
                disabledReason: unfreezeExposureLoading ? 'Unfreezing exposure...' : undefined,
                'data-attr': `${dataAttrPrefix}unfreeze-exposure`,
            },
        showStateActions &&
            !paused && {
                label: 'Pause experiment',
                icon: <IconPause />,
                status: 'danger',
                onClick: () => openPauseExperimentModal(),
                'data-attr': `${dataAttrPrefix}pause-experiment`,
            },
        isExperimentLaunched && {
            label: 'Reset analysis',
            icon: <IconRefresh />,
            status: 'danger',
            onClick: () => confirmResetExperiment(experiment, resetRunningExperiment),
            'data-attr': `${dataAttrPrefix}reset-experiment`,
        },
    ]

    const dangerItems: (LemonMenuItemLeafCallback | false)[] = [
        canArchive && {
            label: 'Archive experiment',
            icon: <IconArchive />,
            onClick: () => confirmArchiveExperiment(experiment, (disableFlag) => archiveExperiment(disableFlag)),
            'data-attr': `${dataAttrPrefix}archive-experiment`,
        },
        canEdit &&
            !!experiment.archived && {
                label: 'Unarchive experiment',
                icon: <IconArchive />,
                onClick: () => unarchiveExperiment(),
                'data-attr': `${dataAttrPrefix}unarchive-experiment`,
            },
        canDelete && {
            label: 'Delete experiment',
            icon: <IconTrash />,
            status: 'danger',
            onClick: () =>
                confirmDeleteExperiment({
                    projectId: currentProjectId,
                    experiment,
                    onDelete: () => router.actions.push(urls.experiments()),
                }),
            'data-attr': `${dataAttrPrefix}delete-experiment`,
        },
    ]

    return [
        { key: 'manage', items: manageItems },
        { key: 'state', items: stateItems },
        { key: 'danger', items: dangerItems },
    ]
        .map((section) => ({
            ...section,
            items: section.items.filter((item): item is LemonMenuItemLeafCallback => !!item),
        }))
        .filter((section) => section.items.length > 0)
}
