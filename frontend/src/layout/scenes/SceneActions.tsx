import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { breadcrumbsLogic } from '../navigation/Breadcrumbs/breadcrumbsLogic'
import { sceneLayoutLogic } from './sceneLayoutLogic'

export function SceneActions(): JSX.Element | null {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')
    const { scenePanelOpen, scenePanelIsPresent, scenePanelIsRelative, forceScenePanelClosedWhenRelative } =
        useValues(sceneLayoutLogic)
    const { setScenePanelOpen, setForceScenePanelClosedWhenRelative } = useActions(sceneLayoutLogic)
    const { setActionsContainer } = useActions(breadcrumbsLogic)

    return !newSceneLayout ? null : (
        <>
            <div className="flex justify-end gap-1">
                <div className="contents" ref={setActionsContainer} />

                {scenePanelIsPresent && (
                    <LemonButton
                        onClick={() =>
                            scenePanelIsRelative
                                ? setForceScenePanelClosedWhenRelative(!forceScenePanelClosedWhenRelative)
                                : setScenePanelOpen(!scenePanelOpen)
                        }
                        icon={<IconEllipsis className="text-primary" />}
                        tooltip={
                            !scenePanelOpen
                                ? 'Open Info & actions panel'
                                : scenePanelIsRelative
                                  ? 'Force close Info & actions panel'
                                  : 'Close Info & actions panel'
                        }
                        aria-label={
                            !scenePanelOpen
                                ? 'Open Info & actions panel'
                                : scenePanelIsRelative
                                  ? 'Force close Info & actions panel'
                                  : 'Close Info & actions panel'
                        }
                        active={scenePanelOpen}
                        size="small"
                    />
                )}
            </div>
        </>
    )
}
