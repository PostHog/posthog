import { useActions, useValues } from 'kea'

import { IconPause, IconPlay, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationSceneMenuBar } from './EvaluationSceneMenuBar'

function StatusTags({
    errored,
    running,
    unsaved,
}: {
    errored: boolean
    running: boolean
    unsaved: boolean
}): JSX.Element {
    return (
        <>
            {errored ? (
                <LemonTag type="danger" icon={<IconWarning />}>
                    Error
                </LemonTag>
            ) : (
                <LemonTag type={running ? 'success' : 'default'}>{running ? 'Running' : 'Paused'}</LemonTag>
            )}
            {unsaved && <LemonTag type="warning">Unsaved changes</LemonTag>}
        </>
    )
}

function RunStateButton({
    running,
    accessLevel,
}: {
    running: boolean
    accessLevel: AccessControlLevel | undefined
}): JSX.Element {
    const { enabledSaving, enableSavedReason } = useValues(llmEvaluationLogic)
    const { saveEnabled } = useActions(llmEvaluationLogic)
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Evaluation}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={accessLevel}
        >
            <LemonButton
                type="secondary"
                size="small"
                icon={running ? <IconPause /> : <IconPlay />}
                onClick={() => saveEnabled(!running)}
                loading={enabledSaving}
                disabledReason={running ? undefined : (enableSavedReason ?? undefined)}
                data-attr="llma-evaluation-header-enabled"
            >
                {running ? 'Pause' : 'Turn on'}
            </LemonButton>
        </AccessControlAction>
    )
}

/** The saved evaluation's title row, its run state, and the actions that change it. */
export function EvaluationSceneHeader({
    playgroundUrl,
    unsaved,
    showSaveAction,
    saveDisabledReason,
    onSave,
    onCancel,
}: {
    playgroundUrl: string | null
    unsaved: boolean
    showSaveAction: boolean
    saveDisabledReason: string | undefined
    onSave: () => void
    onCancel: () => void
}): JSX.Element | null {
    const { evaluation, originalEvaluation, evaluationFormSubmitting } = useValues(llmEvaluationLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sceneMenuBarEnabled = !!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]

    if (!evaluation) {
        return null
    }
    // Pause and Turn on save at once, so they follow the saved state, not an unsaved edit from the configuration tab.
    const running = originalEvaluation?.enabled ?? evaluation.enabled
    const accessLevel = evaluation.user_access_level ?? undefined

    return (
        <>
            {sceneMenuBarEnabled && <EvaluationSceneMenuBar playgroundUrl={playgroundUrl} />}
            <SceneTitleSection
                name={evaluation.name}
                description={evaluation.description || null}
                resourceType={{ type: 'llm_evaluations' }}
                hideProductSetupButton
                nameSuffix={<StatusTags errored={evaluation.status === 'error'} running={running} unsaved={unsaved} />}
                actions={
                    <>
                        {!sceneMenuBarEnabled && playgroundUrl && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlay />}
                                to={playgroundUrl}
                                data-attr="llma-playground-open-from-evaluation"
                            >
                                Open in Playground
                            </LemonButton>
                        )}
                        <RunStateButton running={running} accessLevel={accessLevel} />
                        {unsaved && (
                            <LemonButton type="secondary" size="small" onClick={onCancel}>
                                Cancel
                            </LemonButton>
                        )}
                        {showSaveAction && (
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Evaluation}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={accessLevel}
                            >
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={onSave}
                                    disabledReason={saveDisabledReason}
                                    loading={evaluationFormSubmitting}
                                >
                                    Save changes
                                </LemonButton>
                            </AccessControlAction>
                        )}
                    </>
                }
            />
        </>
    )
}
