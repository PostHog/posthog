import { useActions } from 'kea'

import { IconArchive, IconCopy, IconPencil, IconPeople, IconStar, IconStarFilled, IconTrash } from '@posthog/icons'

import { urls } from 'scenes/urls'

import { ChannelDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { TodayMenuParts } from './todayMenuParts'
import { todaySpacesLogic } from './todaySpacesLogic'

interface TodaySpaceActionsProps {
    parts: TodayMenuParts
    space: ChannelDTOApi
    /** Starts each item's `data-attr`, so every surface counts on its own. */
    dataAttrPrefix: string
}

function autoArchiveActionLabel(days: number | null): string {
    return days === null ? 'Auto-archive: off…' : `Auto-archive: ${days} ${days === 1 ? 'day' : 'days'}…`
}

/** A space's actions, New session first, like the space rows in PostHog Desktop. */
export function TodaySpaceActions({
    parts: { Item, Separator },
    space,
    dataAttrPrefix,
}: TodaySpaceActionsProps): JSX.Element {
    const { toggleStar, copySpaceLink } = useActions(todaySpacesLogic)
    const attr = (name: string): string => `${dataAttrPrefix}-${name}`
    const settingsUrl = urls.taskSpaceSettings(space.id)
    const editable = !space.system_role

    return (
        <>
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
            <Item to={settingsUrl} dataAttr={attr('auto-archive')}>
                <IconArchive />
                {autoArchiveActionLabel(space.auto_archive_after_days)}
            </Item>
            {space.channel_type === 'private' && (
                <Item to={settingsUrl} dataAttr={attr('members')}>
                    <IconPeople />
                    Members
                </Item>
            )}
            {editable && (
                <>
                    <Item to={settingsUrl} dataAttr={attr('rename')}>
                        <IconPencil />
                        Rename space…
                    </Item>
                    <Item to={settingsUrl} variant="destructive" dataAttr={attr('delete')}>
                        <IconTrash />
                        Delete space…
                    </Item>
                </>
            )}
        </>
    )
}
