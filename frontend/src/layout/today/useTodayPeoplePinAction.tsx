import { useActions, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'

import type { SceneAction, SceneActionGroup } from '~/layout/scenes/sceneActions/sceneActionModel'

import { pinTargetKey, sidebarPinsLogic } from './sidebar/sidebarPinsLogic'
import { todayPeopleRecentsLogic } from './todayPeopleRecentsLogic'

/**
 * Pins the person, group, account or ticket the scene shows to the Today sidebar. Empty until the scene reports its
 * loaded record, which happens only under the Today layout. The title's pin button does the same.
 */
export function useTodayPeoplePinAction({
    group = 'edit',
    section,
}: { group?: SceneActionGroup; section?: string } = {}): SceneAction[] {
    const { currentRecent } = useValues(todayPeopleRecentsLogic)
    const { pinnedShortcutIds, shortcutDataLoading } = useValues(sidebarPinsLogic)
    const { togglePinned } = useActions(sidebarPinsLogic)
    if (!currentRecent) {
        return []
    }
    const target = { type: currentRecent.type, name: currentRecent.name, href: currentRecent.href }
    const pinned = pinnedShortcutIds.has(pinTargetKey(target))
    return [
        {
            group,
            section,
            // pinned: data-attr values are wire strings
            id: pinned ? `people-${currentRecent.type}-menubar-unpin` : `people-${currentRecent.type}-menubar-pin`,
            label: pinned ? 'Unpin from sidebar' : 'Pin to sidebar',
            icon: pinned ? <IconPinFilled /> : <IconPin />,
            disabledReason: shortcutDataLoading ? 'Loading pins' : undefined,
            onSelect: () => togglePinned(target),
        },
    ]
}
