import { useValues } from 'kea'
import { router } from 'kea-router'
import { useId, useMemo } from 'react'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { chatVisibility } from './todayChatVisibility'
import { todayListAppearanceLogic } from './todayListAppearanceLogic'
import { sessionPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'
import { TodaySessionBadges } from './TodaySessionBadges'
import { TodaySessionContextMenu } from './TodaySessionContextMenu'
import { TodaySessionDialogs } from './TodaySessionDialogs'
import { TodaySessionIcon } from './TodaySessionIcon'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { TodaySessionRenameInput } from './TodaySessionRenameInput'
import { todaySpacesLogic } from './todaySpacesLogic'
import { TodaySpacesRow } from './TodaySpacesRow'
import { TodayWorkItem, sessionBadges, sessionDetails } from './todayWorkItems'
import { useTodaySidebarBulkSelection } from './useTodaySidebarBulkSelection'

interface TodaySessionRowProps {
    item: TodayWorkItem
    pinned: boolean
    /** False under the Pinned heading, which already says it for every row. */
    showPinBadge: boolean
    dataAttr: string
    surface: TodaySessionSurface
    unread: boolean
    selected?: boolean
    /** Takes a modifier click over for the sidebar's multi-select. */
    onSelectClick?: (event: React.MouseEvent<HTMLElement>) => void
    optionValue: string
}

export function TodaySessionRow({
    item,
    pinned,
    showPinBadge,
    dataAttr,
    surface,
    unread,
    selected = false,
    onSelectClick,
    optionValue,
}: TodaySessionRowProps): JSX.Element {
    const { renaming } = useValues(todaySessionMenuLogic)
    const { location, searchParams } = useValues(router)
    const { user } = useValues(userLogic)
    const { pullRequestStates, spaces } = useValues(todaySpacesLogic)
    const { fields } = useValues(todayListAppearanceLogic)
    const menuId = useId()
    const sidebarSelection = useTodaySidebarBulkSelection()
    const userId = user?.id
    const preview = useMemo(
        () => sessionPreview(item, { unread, pinned, pullRequestStates, spaces, menuId, userId }),
        [item, unread, pinned, pullRequestStates, spaces, menuId, userId]
    )
    const details = useMemo(() => sessionDetails(item, fields, spaces), [item, fields, spaces])

    const pinBadge = pinned && showPinBadge
    const visibility = useMemo(() => chatVisibility(item.channel, spaces), [item.channel, spaces])
    const badges = useMemo(
        () => sessionBadges(item, userId, { pinned: pinBadge, visibility }),
        [item, userId, pinBadge, visibility]
    )
    const [pullRequest] = item.pullRequests
    const badgeCount = badges.length + (pinBadge ? 1 : 0)

    if (renaming?.sessionId === item.id && renaming.surface === surface) {
        return <TodaySessionRenameInput sessionId={item.id} title={item.title} />
    }
    const row = (
        <TodaySpacesRow
            label={item.title || 'Untitled session'}
            // Unread shows only as a solid status dot; the title keeps its resting weight, like desktop.
            icon={<TodaySessionIcon item={item} unread={unread} />}
            to={urls.aiTask(item.id)}
            active={location.pathname.endsWith('/ai') && searchParams.task === item.id}
            dataAttr={dataAttr}
            badge={
                badgeCount > 0 ? (
                    <TodaySessionBadges
                        badges={badges}
                        pullRequestState={pullRequest ? pullRequestStates[pullRequest.url] : null}
                        pinned={pinBadge}
                    />
                ) : null
            }
            badgeCount={badgeCount >= 3 ? 3 : badgeCount === 2 ? 2 : 1}
            ticker
            selected={selected}
            onClickCapture={onSelectClick}
            details={details}
            optionValue={optionValue}
        />
    )
    // Like Desktop, the row's actions live in its hover card and its right-click menu, which open the dialogs on the row's behalf.
    return (
        <>
            <TodaySessionContextMenu target={preview.menu} surface={surface} selection={sidebarSelection}>
                <TodayPreviewTrigger payload={preview}>{row}</TodayPreviewTrigger>
            </TodaySessionContextMenu>
            <TodaySessionDialogs target={preview.menu} />
        </>
    )
}
