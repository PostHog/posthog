import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'

import { SceneMenuBarItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'

import { newEventsTableLogic } from './newEventsTableLogic'

export function NewEventsTableSceneMenu({ dataAttrKey }: { dataAttrKey: string }): JSX.Element | null {
    const { newEventsTableAvailable } = useValues(newEventsTableLogic)
    const { openEventsTableTab } = useActions(newEventsTableLogic)

    if (!newEventsTableAvailable) {
        return null
    }

    return (
        <SceneMenuBarMenu label="Staff only" dataAttr={`${dataAttrKey}-menubar-staff`}>
            <SceneMenuBarItem
                onClick={() => openEventsTableTab(true)}
                data-attr={`${dataAttrKey}-menubar-open-new-events-table`}
            >
                <IconExternal />
                Open with new events table
            </SceneMenuBarItem>
            <SceneMenuBarItem
                onClick={() => openEventsTableTab(false)}
                data-attr={`${dataAttrKey}-menubar-open-classic-events-table`}
            >
                <IconExternal />
                Open with classic events table
            </SceneMenuBarItem>
        </SceneMenuBarMenu>
    )
}
