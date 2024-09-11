import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { JSONViewer } from 'lib/components/JSONViewer'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { useEffect } from 'react'
import { eventWithTime } from 'rrweb'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function PlayerSidebarDebuggerTab(): JSX.Element {
    const { debugSnapshots } = useValues(sessionRecordingPlayerLogic)
    const { setPause, seekToTimestamp } = useActions(sessionRecordingPlayerLogic)

    useEffect(() => {
        setPause()
    })

    if (!debugSnapshots) {
        return <div>Not ready yet</div>
    }

    const onClick = (snapshot: eventWithTime | null): void => {
        if (snapshot) {
            seekToTimestamp(snapshot.timestamp)
        }
    }

    const { previous, current, next } = debugSnapshots

    return (
        <div className="h-full bg-bg-3000 overflow-auto">
            <div className="p-2 flex gap-1">
                <LemonButton
                    onClick={() => onClick(previous)}
                    icon={<IconChevronLeft />}
                    disabledReason={!previous ? "You're on the first snapshot" : null}
                    type="secondary"
                    size="xsmall"
                >
                    Previous
                </LemonButton>
                <LemonButton
                    onClick={() => onClick(next)}
                    icon={<IconChevronRight />}
                    disabledReason={!next ? "You're on the last snapshot" : null}
                    type="secondary"
                    size="xsmall"
                >
                    Next
                </LemonButton>
            </div>

            <div className="border-y">
                <LemonCollapse
                    size="xsmall"
                    multiple
                    embedded
                    panels={[
                        {
                            key: 'previous',
                            header: 'Previous snapshot',
                            content: previous && <JSONViewer src={previous} />,
                        },
                        {
                            key: 'current',
                            header: 'Current snapshot',
                            content: <JSONViewer src={current} />,
                        },
                        {
                            key: 'next',
                            header: 'Next snapshot',
                            content: next && <JSONViewer src={next} />,
                        },
                    ]}
                />
            </div>
        </div>
    )
}
