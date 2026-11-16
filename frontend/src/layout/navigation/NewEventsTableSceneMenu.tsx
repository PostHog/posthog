import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'

import {
    SceneMenuBarCheckboxItem,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'

import { newEventsTableLogic } from './newEventsTableLogic'

export function NewEventsTableSceneMenu({ dataAttrKey }: { dataAttrKey: string }): JSX.Element | null {
    const { newEventsTableAvailable, newEventsTableEnabled } = useValues(newEventsTableLogic)
    const { setNewEventsTable, openOtherEventsTableTab } = useActions(newEventsTableLogic)

    if (!newEventsTableAvailable) {
        return null
    }

    return (
        <SceneMenuBarMenu label="Staff only" dataAttr={`${dataAttrKey}-menubar-staff`}>
            <SceneMenuBarItem
                onClick={openOtherEventsTableTab}
                data-attr={`${dataAttrKey}-menubar-open-other-events-table`}
            >
                <IconExternal />
                <span>{newEventsTableEnabled ? 'Open with classic events table' : 'Open with new events table'}</span>
            </SceneMenuBarItem>
            <SceneMenuBarSeparator />
            <SceneMenuBarCheckboxItem
                checked={newEventsTableEnabled}
                onCheckedChange={setNewEventsTable}
                data-attr={`${dataAttrKey}-menubar-new-events-table`}
            >
                New events table
            </SceneMenuBarCheckboxItem>
        </SceneMenuBarMenu>
    )
}
