import { useActions } from 'kea'

import { IconCopy, IconGear, IconPlus, IconStar, IconStarFilled } from '@posthog/icons'

import { urls } from 'scenes/urls'

import { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { TodayMenuParts } from './todayMenuParts'
import { spaceNewSessionUrl, todaySpacesLogic } from './todaySpacesLogic'

interface TodaySpaceActionsProps {
    parts: TodayMenuParts
    space: ChannelDTOApi
    /** Starts each item's `data-attr`, so every surface counts on its own. */
    dataAttrPrefix: string
}

/** A space's actions, New session first, like the space rows in PostHog Desktop. */
export function TodaySpaceActions({
    parts: { Item, Separator },
    space,
    dataAttrPrefix,
}: TodaySpaceActionsProps): JSX.Element {
    const { toggleStar, copySpaceLink } = useActions(todaySpacesLogic)
    const attr = (name: string): string => `${dataAttrPrefix}-${name}`

    return (
        <>
            <Item to={spaceNewSessionUrl(space.id)} dataAttr={attr('new-session')}>
                <IconPlus />
                New session
            </Item>
            {space.system_role !== 'personal' && (
                <Item onClick={() => toggleStar(space.id, !space.starred)} dataAttr={attr('star')}>
                    {space.starred ? <IconStarFilled /> : <IconStar />}
                    {space.starred ? 'Unstar space' : 'Star space'}
                </Item>
            )}
            <Item onClick={() => copySpaceLink(space.id)} dataAttr={attr('copy-link')}>
                <IconCopy />
                Copy link
            </Item>
            <Separator />
            <Item to={urls.taskSpaceSettings(space.id)} dataAttr={attr('settings')}>
                <IconGear />
                Space settings
            </Item>
        </>
    )
}
