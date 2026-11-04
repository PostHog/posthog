import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear, IconPause, IconPlay, IconTrends } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { sceneFileLogic } from 'lib/components/Scenes/sceneFileLogic'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmEvaluationLogic } from '../llmEvaluationLogic'

/** The evaluation page's menu bar. The caller renders it only behind the scene menu bar flag. */
export function EvaluationSceneMenuBar({ playgroundUrl }: { playgroundUrl: string | null }): JSX.Element | null {
    const { originalEvaluation, enabledSaving, canEnable, canEnableReason, trendInsightUrl } =
        useValues(llmEvaluationLogic)
    const { saveEnabled, setActiveTab } = useActions(llmEvaluationLogic)
    const { hasFileItems } = useValues(sceneFileLogic)

    if (!originalEvaluation) {
        return null
    }
    const running = originalEvaluation.enabled

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr="llma-evaluation-menubar-file" disabled={!hasFileItems}>
                {hasFileItems && <SceneMenuBarFileItems dataAttrKey="llm_evaluation" />}
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="Edit" dataAttr="llma-evaluation-menubar-edit">
                <SceneMenuBarItem
                    onClick={() => setActiveTab('configuration')}
                    data-attr="llma-evaluation-menubar-configure"
                >
                    <IconGear />
                    Edit configuration
                </SceneMenuBarItem>
                <SceneMenuBarSeparator />
                <AccessControlAction
                    resourceType={AccessControlResourceType.Evaluation}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={originalEvaluation.user_access_level ?? undefined}
                >
                    {({ disabledReason }) => {
                        const reason = disabledReason ?? (!running && !canEnable ? canEnableReason : null)
                        return (
                            <SceneMenuBarItem
                                onClick={() => saveEnabled(!running)}
                                disabled={!!reason || enabledSaving}
                                tooltip={reason ?? undefined}
                                data-attr="llma-evaluation-menubar-enabled"
                            >
                                {running ? <IconPause /> : <IconPlay />}
                                {running ? 'Pause' : 'Turn on'}
                            </SceneMenuBarItem>
                        )
                    }}
                </AccessControlAction>
            </SceneMenuBarMenu>
            <SceneMenuBarMenu
                label="View"
                dataAttr="llma-evaluation-menubar-view"
                disabled={!trendInsightUrl && !playgroundUrl}
            >
                {trendInsightUrl && (
                    <SceneMenuBarItem
                        onClick={() => window.open(trendInsightUrl, '_blank', 'noopener,noreferrer')}
                        data-attr="llma-evaluation-menubar-trend-insight"
                    >
                        <IconTrends />
                        Trend insight
                    </SceneMenuBarItem>
                )}
                {playgroundUrl && (
                    <SceneMenuBarItem
                        onClick={() => router.actions.push(playgroundUrl)}
                        data-attr="llma-evaluation-menubar-playground"
                    >
                        <IconPlay />
                        Open in Playground
                    </SceneMenuBarItem>
                )}
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
