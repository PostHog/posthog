import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconChevronDown, IconCopy, IconGlobe, IconLock, IconPeople } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { TodayChatVisibility, chatVisibility } from './todayChatVisibility'
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
    ownerName: string | null
}

function visibilityHint({
    visibility,
    mine,
    ownerName,
    project,
    spaceName,
}: {
    visibility: TodayChatVisibility
    mine: boolean
    ownerName: string | null
    project: string
    spaceName: string | undefined
}): string {
    if (visibility === 'personal') {
        return 'Only you can see this chat.'
    }
    if (visibility === 'shared') {
        return `This chat is in ${spaceName ? `the older space ${spaceName}` : 'an older space'}. Only its members can see it.`
    }
    return mine
        ? `Everyone in ${project} can see this chat.`
        : `${ownerName ?? 'A teammate'} started this public chat. Everyone in ${project} can see it.`
}

export function TodayChatVisibilityButton({
    taskId,
    title,
    spaceId,
    ownerId,
    ownerName,
}: TodayChatVisibilityButtonProps): JSX.Element | null {
    const { spaces, personalSpaceId, publicSpaceId } = useValues(todaySpacesLogic)
    const { movedSessionSpaces, makePublicRequest, pendingSessionIds } = useValues(todaySessionMenuLogic)
    const { requestMakePublic, setSessionVisibility, copySessionLink } = useActions(todaySessionMenuLogic)
    const { phoneLayout } = useValues(todayShellLogic)
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const [sheetOpen, setSheetOpen] = useState(false)
    const menuId = useId()

    if (spaces.length === 0) {
        return null
    }

    const currentSpaceId = movedSessionSpaces[taskId] ?? spaceId
    const visibility = chatVisibility(currentSpaceId, spaces)
    const pending = pendingSessionIds.includes(taskId)
    const mine = ownerId !== null && ownerId === user?.id
    const hint = visibilityHint({
        visibility,
        mine,
        ownerName,
        project: currentTeam?.name || 'this project',
        spaceName: spaces.find((space) => space.id === currentSpaceId)?.name,
    })
    const withHint = (trigger: JSX.Element, content: JSX.Element): JSX.Element => (
        <Tooltip>
            <TooltipTrigger delay={300} render={trigger}>
                {content}
            </TooltipTrigger>
            <TooltipContent className="max-w-72">{hint}</TooltipContent>
        </Tooltip>
    )
    const label = visibility === 'public' ? 'Public' : 'Shared'
    const icon = visibility === 'public' ? <IconGlobe /> : <IconPeople />

    if (!mine) {
        return visibility === 'personal'
            ? null
            : withHint(
                  <span tabIndex={0} className="inline-flex rounded-sm" />,
                  <Badge data-attr="today-chat-header-visibility-readonly">
                      {icon}
                      {label}
                  </Badge>
              )
    }

    const dialog = makePublicRequest?.menuId === menuId && (
        <TodayMakePublicDialog sessionId={taskId} title={title} previousSpaceId={currentSpaceId} />
    )

    if (visibility === 'personal') {
        return (
            <>
                {withHint(
                    <Button
                        variant="outline"
                        size="sm"
                        disabled={!publicSpaceId || pending}
                        onClick={() => requestMakePublic(menuId, 'header')}
                        data-attr="today-chat-header-make-public"
                    />,
                    <>
                        <IconGlobe />
                        Make public
                    </>
                )}
                {dialog}
            </>
        )
    }

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
        'data-attr': 'today-chat-header-visibility',
    } as const
    const content = (
        <>
            {icon}
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
                <TodaySheetMenu open={sheetOpen} onOpenChange={setSheetOpen} title={`${label} chat`} description={hint}>
                    {items(SHEET_PARTS)}
                </TodaySheetMenu>
                {dialog}
            </>
        )
    }

    return (
        <>
            <DropdownMenu>
                {withHint(
                    <span className="inline-flex" />,
                    <DropdownMenuTrigger render={<Button {...triggerProps} />}>{content}</DropdownMenuTrigger>
                )}
                <DropdownMenuContent align="end" className="min-w-52">
                    {items(DROPDOWN_PARTS)}
                </DropdownMenuContent>
            </DropdownMenu>
            {dialog}
        </>
    )
}
