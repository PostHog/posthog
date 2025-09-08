import { LemonDivider } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function SceneDivider(): JSX.Element | null {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    // If not in new scene layout, we don't want to show anything new
    if (!newSceneLayout) {
        return null
    }

    return <LemonDivider className="scene-divider -mx-4 w-[calc(100%+var(--spacing)*8)]" />
}
