import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'

import { useExperimentActions } from './useExperimentActions'

export function ExperimentActionsMenu(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')

    // The scene menu bar already surfaces every action in its File/Edit menus.
    if (sceneMenuBarEnabled) {
        return null
    }

    return <ExperimentActionsMenuInner />
}

function ExperimentActionsMenuInner(): JSX.Element | null {
    const sections = useExperimentActions('actions-dropdown-')

    if (sections.length === 0) {
        return null
    }

    return (
        <LemonMenu items={sections} placement="bottom-end">
            <LemonButton
                type="secondary"
                size="small"
                sideIcon={<IconChevronDown />}
                data-attr="experiment-actions-menu"
            >
                Actions
            </LemonButton>
        </LemonMenu>
    )
}
