import { cn } from '@posthog/quill'

import { SceneAction, pinnedSceneActions } from './sceneActionModel'
import { ScenePinnedAction } from './ScenePinnedAction'

/**
 * The title row's buttons, derived from the scene's actions. A narrow scene keeps only the last one, the primary
 * action when there is one: every pinned action is also in the "More actions" menu, so folding loses nothing.
 */
export function ScenePinnedActions({ actions }: { actions: SceneAction[] }): JSX.Element | null {
    const pinned = pinnedSceneActions(actions)
    if (pinned.length === 0) {
        return null
    }
    return (
        <div data-attr="scene-pinned-actions" className="flex items-center gap-1">
            {pinned.map((action, index) => (
                <span
                    key={action.id}
                    className={cn('contents', index < pinned.length - 1 && '@max-3xl/main-content:hidden')}
                >
                    <ScenePinnedAction action={action} />
                </span>
            ))}
        </div>
    )
}
