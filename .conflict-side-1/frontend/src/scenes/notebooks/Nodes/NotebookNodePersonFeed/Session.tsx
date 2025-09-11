import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCollapse, IconExpand, IconRewindPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDetailedTime, humanFriendlyDuration } from 'lib/utils'
import { NotebookNodeType } from 'scenes/notebooks/types'

import { notebookNodeLogic } from '../notebookNodeLogic'
import { SessionEvent } from './SessionEvent'

type SessionProps = {
    session: any // TimelineEntry
}

export const Session = ({ session }: SessionProps): JSX.Element => {
    const { children, nodeId } = useValues(notebookNodeLogic)
    const { updateAttributes } = useActions(notebookNodeLogic)

    const startTime = dayjs(session.events[0].timestamp)
    const endTime = dayjs(session.events[session.events.length - 1].timestamp)
    const durationSeconds = endTime.diff(startTime, 'second')

    const [isFolded, setIsFolded] = useState(false)

    const onOpenReplay = (): void => {
        const newChildren = [...(children || [])]

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
        <div className="flex flex-col rounded bg-primary border overflow-hidden mb-3" title={session.sessionId}>
            <div className="flex items-center justify-between bg-surface-primary p-0.5 pr-2 text-xs">
                <div className="flex items-center">
                    <LemonButton
                        size="small"
                        icon={isFolded ? <IconExpand /> : <IconCollapse />}
                        onClick={() => setIsFolded((state) => !state)}
                    />
                    <span className="font-bold ml-2">{humanFriendlyDetailedTime(startTime)}</span>
                </div>
                <div className="flex items-center">
                    <span>
                        <b>{session.events.length} events</b> in <b>{humanFriendlyDuration(durationSeconds)}</b>
                    </span>
                    {session.recording_duration_s ? (
                        <LemonButton
                            className="ml-1"
                            size="small"
                            icon={<IconRewindPlay />}
                            onClick={() => onOpenReplay()}
                        />
                    ) : null}
                </div>
            </div>
            {!isFolded && (
                <div className="p-1 border-t deprecated-space-y-1">
                    {session.events.map((event: any) => (
                        <SessionEvent key={event.id} event={event} />
                    ))}
                </div>
            )}
        </div>
    )
}
