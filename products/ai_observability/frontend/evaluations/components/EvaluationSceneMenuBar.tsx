import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear, IconPause, IconPlay, IconTrends, IconX } from '@posthog/icons'

import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmEvaluationLogic } from '../llmEvaluationLogic'

const RESOURCE_TYPE = 'llma-evaluation'

interface EvaluationSceneMenuBarProps {
    playgroundUrl: string | null
    unsaved: boolean
    showSaveAction: boolean
    saveDisabledReason: string | undefined
    onSave: () => void
    onCancel: () => void
}

/** The evaluation page's menu bar. The caller renders it only behind the scene menu bar flag. */
export function EvaluationSceneMenuBar({
    playgroundUrl,
    unsaved,
    showSaveAction,
    saveDisabledReason,
    onSave,
    onCancel,
}: EvaluationSceneMenuBarProps): JSX.Element | null {
    const { originalEvaluation, enabledSaving, enableSavedReason, trendInsightUrl, evaluationFormSubmitting } =
        useValues(llmEvaluationLogic)
    const { saveEnabled, setActiveTab } = useActions(llmEvaluationLogic)
    const fileActions = useSceneFileActions('llm_evaluation')

    if (!originalEvaluation) {
        return null
    }
    const running = originalEvaluation.enabled
    const accessDisabledReason =
        getAccessControlDisabledReason(
            AccessControlResourceType.Evaluation,
            AccessControlLevel.Editor,
            originalEvaluation.user_access_level ?? undefined
        ) ?? undefined
    const runStateDisabledReason =
        accessDisabledReason ||
        (!running && enableSavedReason) ||
        (enabledSaving ? 'Saving the run state' : undefined) ||
        undefined
    const saveReason =
        accessDisabledReason ?? saveDisabledReason ?? (evaluationFormSubmitting ? 'Saving changes' : undefined)

    const actions: SceneAction[] = [
        ...fileActions,
        {
            group: 'edit',
            id: `${RESOURCE_TYPE}-menubar-configure`,
            label: 'Edit configuration',
            icon: <IconGear />,
            onSelect: () => setActiveTab('configuration'),
        },
        ...(showSaveAction
            ? ([
                  {
                      group: 'edit',
                      section: 'save',
                      id: `${RESOURCE_TYPE}-menubar-save`,
                      label: 'Save changes',
                      disabledReason: saveReason,
                      onSelect: onSave,
                      pinned: { order: 3, variant: 'primary' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(unsaved
            ? ([
                  {
                      group: 'edit',
                      section: 'save',
                      id: `${RESOURCE_TYPE}-menubar-cancel`,
                      label: 'Cancel',
                      icon: <IconX />,
                      onSelect: onCancel,
                      pinned: { order: 2, variant: 'secondary' },
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'edit',
            section: 'state',
            id: `${RESOURCE_TYPE}-menubar-enabled`,
            label: running ? 'Pause' : 'Turn on',
            icon: running ? <IconPause /> : <IconPlay />,
            disabledReason: runStateDisabledReason,
            onSelect: () => saveEnabled(!running),
            pinned: { order: 1, variant: 'secondary', dataAttr: 'llma-evaluation-header-enabled' },
        },
        ...(trendInsightUrl
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-trend-insight`,
                      label: 'Trend insight',
                      icon: <IconTrends />,
                      onSelect: () => window.open(trendInsightUrl, '_blank', 'noopener,noreferrer'),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(playgroundUrl
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-playground`,
                      label: 'Open in Playground',
                      icon: <IconPlay />,
                      onSelect: () => router.actions.push(playgroundUrl),
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
