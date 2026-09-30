import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    IconArchive,
    IconEllipsis,
    IconFolderMove,
    IconPencil,
    IconPin,
    IconPinFilled,
    IconSearch,
    IconSend,
} from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { TodaySessionHandoffModal } from './TodaySessionHandoffModal'
import { TodaySessionSurface, todaySessionMenuLogic } from './todaySessionMenuLogic'
import { spaceLabel, todaySpacesLogic } from './todaySpacesLogic'

interface TodaySessionMenuProps {
    sessionId: string
    pinned: boolean
    spaceId: string | null
    surface: TodaySessionSurface
    canHandOff?: boolean
    analysisRunId?: string | null
}

export function TodaySessionMenu({
    sessionId,
    pinned,
    spaceId,
    surface,
    canHandOff = false,
    analysisRunId = null,
}: TodaySessionMenuProps): JSX.Element {
    const menuId = useId()
    const { featureFlags } = useValues(featureFlagLogic)
    const { sortedSpaces } = useValues(todaySpacesLogic)
    const { pendingSessionIds, handoffMenuId } = useValues(todaySessionMenuLogic)
    const { setSessionPinned, startRenaming, archiveSession, moveSession, openHandoff, analyzeSession } =
        useActions(todaySessionMenuLogic)
    const runId = featureFlags[FEATURE_FLAGS.POSTHOG_CODE_TASK_ANALYSIS] ? analysisRunId : null
    const disabledReason = pendingSessionIds.includes(sessionId) ? 'Saving your last change' : undefined
    const otherSpaces = sortedSpaces.filter((space) => space.id !== spaceId)

    return (
        <>
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
                    runId
                        ? {
                              label: 'Run analysis',
                              icon: <IconSearch />,
                              onClick: () => analyzeSession(sessionId, runId),
                              disabledReason,
                              'data-attr': 'today-session-analyze',
                          }
                        : null,
                    canHandOff
                        ? {
                              label: 'Hand off…',
                              icon: <IconSend />,
                              onClick: () => openHandoff(menuId),
                              disabledReason,
                              'data-attr': 'today-session-handoff',
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
            {canHandOff && handoffMenuId === menuId && <TodaySessionHandoffModal sessionId={sessionId} />}
        </>
    )
}
