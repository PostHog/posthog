import { useState } from 'react'
import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { IconRewindPlay } from '@posthog/icons'
import { dayjs } from 'lib/dayjs'
import { TimelineEntry } from '~/queries/schema'
import { NotebookNodeType } from '~/types'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime, humanFriendlyDuration } from 'lib/utils'
import { SessionEvent } from './SessionEvent'
import { notebookNodeLogic } from '../notebookNodeLogic'

type SessionProps = {
    session: TimelineEntry
}

export const Session = ({ session }: SessionProps): JSX.Element => {
    const { children, nodeId } = useValues(notebookNodeLogic)
    const { updateAttributes } = useActions(notebookNodeLogic)

    const startTime = dayjs(session.events[session.events.length - 1].timestamp)
    const endTime = dayjs(session.events[0].timestamp)
    const durationSeconds = endTime.diff(startTime, 'second')

    const [isFolded, setIsFolded] = useState(false)

    const onOpenReplay = (): void => {
        const newChildren = [...children] || []

        const existingChild = newChildren.find((child) => child.attrs?.nodeId === `${nodeId}-active-replay`)

        if (existingChild) {
            existingChild.attrs.id = session.sessionId
        } else {
            newChildren.splice(0, 0, {
                type: NotebookNodeType.Recording,
                attrs: {
                    id: session.sessionId,
                    nodeId: `${nodeId}-active-replay`,
                    height: '5rem',
                    __init: {
                        expanded: true,
                    },
                },
            })
        }

        updateAttributes({
            children: newChildren,
        })
    }

    return (
        <div className="flex flex-col rounded bg-side border overflow-hidden mb-3" title={session.sessionId}>
            <div className="flex items-center justify-between pl-2 pr-4 py-2 gap-2 bg-bg-light">
                <div className="flex items-center">
                    <LemonButton
                        size="small"
                        icon={isFolded ? <IconUnfoldMore /> : <IconUnfoldLess />}
                        status="stealth"
                        onClick={() => setIsFolded((state) => !state)}
                    />
                    <b className="ml-2">{humanFriendlyDetailedTime(startTime)}</b>
                    <span className="text-muted-3000 font-bold ml-1">({session.events.length} events)</span>
                </div>
                <div className="flex items-center flex-1">
                    <span>{humanFriendlyDuration(durationSeconds)}</span>
                </div>
                {session.recording_duration_s ? (
                    <LemonButton size="small" icon={<IconRewindPlay />} onClick={() => onOpenReplay()} />
                ) : null}
            </div>
            {!isFolded && (
                <div className="p-2 border-t space-y-2">
                    {session.events.map((event) => (
                        <SessionEvent key={event.id} event={event} />
                    ))}
                </div>
            )}
        </div>
    )
}
