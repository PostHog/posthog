import { useActions, useValues } from 'kea'

import { IconArchive, IconEllipsis, IconFolderMove, IconPencil, IconPin, IconPinFilled } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { spaceLabel, todaySpacesLogic } from './todaySpacesLogic'

interface TodaySessionMenuProps {
    sessionId: string
    pinned: boolean
    spaceId: string | null
    surface: TodaySessionSurface
}

export function TodaySessionMenu({ sessionId, pinned, spaceId, surface }: TodaySessionMenuProps): JSX.Element {
    const { sortedSpaces } = useValues(todaySpacesLogic)
    const { pendingSessionIds } = useValues(todaySessionMenuLogic)
    const { setSessionPinned, startRenaming, archiveSession, moveSession } = useActions(todaySessionMenuLogic)
    const disabledReason = pendingSessionIds.includes(sessionId) ? 'Saving your last change' : undefined
    const otherSpaces = sortedSpaces.filter((space) => space.id !== spaceId)

    return (
        <LemonMenu
            items={[
                {
                    label: pinned ? 'Unpin' : 'Pin',
                    icon: pinned ? <IconPinFilled /> : <IconPin />,
                    onClick: () => setSessionPinned(sessionId, !pinned),
                    disabledReason,
                    'data-attr': 'today-session-pin',
                },
                {
                    label: 'Rename',
                    icon: <IconPencil />,
                    onClick: () => startRenaming(sessionId, surface),
                    disabledReason,
                    'data-attr': 'today-session-rename',
                },
                otherSpaces.length
                    ? {
                          label: 'Move to space',
                          icon: <IconFolderMove />,
                          items: otherSpaces.map((space) => ({
                              label: spaceLabel(space),
                              onClick: () => moveSession(sessionId, space.id),
                              disabledReason,
                              'data-attr': 'today-session-move',
                          })),
                      }
                    : null,
                {
                    label: 'Archive',
                    icon: <IconArchive />,
                    onClick: () => archiveSession(sessionId, true),
                    disabledReason,
                    'data-attr': 'today-session-archive',
                },
            ]}
        >
            <LemonButton size="xsmall" icon={<IconEllipsis />} tooltip="More" data-attr="today-session-menu" />
        </LemonMenu>
    )
}
