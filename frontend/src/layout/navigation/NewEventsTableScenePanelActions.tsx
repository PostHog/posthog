import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { ScenePanelActionsSection, ScenePanelDivider } from '~/layout/scenes/SceneLayout'

import { newEventsTableLogic } from './newEventsTableLogic'
import { NewEventsTableSwitch } from './NewEventsTableSwitch'

export function NewEventsTableScenePanelActions({ dataAttrKey }: { dataAttrKey: string }): JSX.Element | null {
    const { newEventsTableAvailable, newEventsTableEnabled } = useValues(newEventsTableLogic)
    const { openOtherEventsTableTab } = useActions(newEventsTableLogic)

    if (!newEventsTableAvailable) {
        return null
    }

    return (
        <>
            <ScenePanelDivider />
            <ScenePanelActionsSection>
                <NewEventsTableSwitch />
                <ButtonPrimitive
                    menuItem
                    onClick={openOtherEventsTableTab}
                    data-attr={`${dataAttrKey}-open-other-events-table`}
                >
                    <IconExternal />
                    <span>
                        {newEventsTableEnabled ? 'Open with classic events table' : 'Open with new events table'}
                    </span>
                </ButtonPrimitive>
            </ScenePanelActionsSection>
        </>
    )
}
