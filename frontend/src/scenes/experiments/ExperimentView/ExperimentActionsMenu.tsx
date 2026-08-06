import { useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useExperimentActions } from './useExperimentActions'

export function ExperimentActionsMenu(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const sections = useExperimentActions('actions-dropdown-')

    // The scene menu bar already surfaces every action in its File/Edit menus.
    if (featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR] || sections.length === 0) {
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
