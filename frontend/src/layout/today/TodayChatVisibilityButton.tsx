import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconChevronDown, IconCopy, IconGlobe, IconLock, IconPeople } from '@posthog/icons'
import { Badge, Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { userLogic } from 'scenes/userLogic'

import { chatVisibility } from './todayChatVisibility'
import { TodayMakePublicDialog } from './TodayMakePublicDialog'
import { DROPDOWN_PARTS, SHEET_PARTS, TodayMenuParts } from './todayMenuParts'
import { todaySessionMenuLogic } from './todaySessionMenuLogic'
import { TodaySheetMenu } from './TodaySheetMenu'
import { todayShellLogic } from './todayShellLogic'
import { todaySpacesLogic } from './todaySpacesLogic'

interface TodayChatVisibilityButtonProps {
    taskId: string
    title: string
    spaceId: string | null
    ownerId: number | null
}

export function TodayChatVisibilityButton({
    taskId,
    title,
    spaceId,
    ownerId,
}: TodayChatVisibilityButtonProps): JSX.Element | null {
    const { spaces, personalSpaceId, publicSpaceId } = useValues(todaySpacesLogic)
    const { movedSessionSpaces, makePublicRequest, pendingSessionIds } = useValues(todaySessionMenuLogic)
    const { requestMakePublic, setSessionVisibility, copySessionLink } = useActions(todaySessionMenuLogic)
    const { phoneLayout } = useValues(todayShellLogic)
    const { user } = useValues(userLogic)
    const [sheetOpen, setSheetOpen] = useState(false)
    const menuId = useId()

    if (spaces.length === 0) {
        return null
    }

    const currentSpaceId = movedSessionSpaces[taskId] ?? spaceId
    const visibility = chatVisibility(currentSpaceId, spaces)
    const pending = pendingSessionIds.includes(taskId)

    if (ownerId === null || ownerId !== user?.id) {
        return visibility === 'personal' ? null : (
            <Badge data-attr="today-chat-header-visibility-readonly">
                {visibility === 'public' ? <IconGlobe /> : <IconPeople />}
                {visibility === 'public' ? 'Public' : 'Shared'}
            </Badge>
        )
    }
    const dialog = makePublicRequest?.menuId === menuId && (
        <TodayMakePublicDialog sessionId={taskId} title={title} previousSpaceId={currentSpaceId} />
    )

    if (visibility === 'personal') {
        return (
            <>
                <Button
                    variant="outline"
                    size="sm"
                    disabled={!publicSpaceId || pending}
                    onClick={() => requestMakePublic(menuId, 'header')}
                    data-attr="today-chat-header-make-public"
                >
                    <IconGlobe />
                    Make public
                </Button>
                {dialog}
            </>
        )
    }

    const label = visibility === 'public' ? 'Public' : 'Shared'
    const items = ({ Item }: TodayMenuParts): JSX.Element => (
        <>
            {visibility === 'shared' && publicSpaceId && (
                <Item onClick={() => requestMakePublic(menuId, 'header')} dataAttr="today-chat-header-make-public">
                    <IconGlobe />
                    Make public…
                </Item>
            )}
            {personalSpaceId && (
                <Item
                    onClick={() => setSessionVisibility(taskId, 'personal', currentSpaceId, 'header')}
                    disabled={pending}
                    dataAttr="today-chat-header-move-to-personal"
                >
                    <IconLock />
                    Move to personal
                </Item>
            )}
            <Item onClick={() => copySessionLink(taskId)} dataAttr="today-chat-header-copy-link">
                <IconCopy />
                Copy link
            </Item>
        </>
    )
    const triggerProps = {
        variant: 'outline',
        size: 'sm',
        loading: pending,
        'aria-label':
            visibility === 'public'
                ? 'Public: everyone in the project can see this chat'
                : 'Shared: members of an older space can see this chat',
        'data-attr': 'today-chat-header-visibility',
    } as const
    const content = (
        <>
            {visibility === 'public' ? <IconGlobe /> : <IconPeople />}
            {label}
            <IconChevronDown />
        </>
    )

    if (phoneLayout) {
        return (
            <>
                <Button {...triggerProps} onClick={() => setSheetOpen(true)}>
                    {content}
                </Button>
                <TodaySheetMenu open={sheetOpen} onOpenChange={setSheetOpen} title={`${label} chat`}>
                    {items(SHEET_PARTS)}
                </TodaySheetMenu>
                {dialog}
            </>
        )
    }

    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger render={<Button {...triggerProps} />}>{content}</DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-52">
                    {items(DROPDOWN_PARTS)}
                </DropdownMenuContent>
            </DropdownMenu>
            {dialog}
        </>
    )
}
