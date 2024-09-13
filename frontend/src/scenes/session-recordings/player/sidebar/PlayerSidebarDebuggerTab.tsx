import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { JSONViewer } from 'lib/components/JSONViewer'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { useEffect, useState } from 'react'
import { EventType, eventWithTime } from 'rrweb'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

const snapshotTypes = {
    0: 'DomContentLoaded',
    1: 'Load',
    2: 'FullSnapshot',
    3: 'IncrementalSnapshot',
    4: 'Meta',
    5: 'Custom',
    6: 'Plugin',
}

const incrementalSource = {
    0: 'Mutation',
    1: 'MouseMove',
    2: 'MouseInteraction',
    3: 'Scroll',
    4: 'ViewportResize',
    5: 'Input',
    6: 'TouchMove',
    7: 'MediaInteraction',
    8: 'StyleSheetRule',
    9: 'CanvasMutation',
    10: 'Font',
    11: 'Log',
    12: 'Drag',
    13: 'StyleDeclaration',
    14: 'Selection',
    15: 'AdoptedStyleSheet',
    16: 'CustomElement',
}

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
                            content: <Snapshot description="previous" snapshot={previous} />,
                        },
                        {
                            key: 'current',
                            header: 'Current snapshot',
                            content: <Snapshot snapshot={current} />,
                        },
                        {
                            key: 'next',
                            header: 'Next snapshot',
                            content: <Snapshot description="next" snapshot={next} />,
                        },
                    ]}
                />
            </div>
        </div>
    )
}

const Snapshot = ({ snapshot, description }: { snapshot: eventWithTime | null; description?: string }): JSX.Element => {
    const [open, setOpen] = useState<boolean>(false)
    if (!snapshot) {
        return <span>This is no {description} snapshot</span>
    }

    const snapshotSummary: Record<string, any> = {
        'formatted time': new Date(snapshot.timestamp).toISOString(),
        type: snapshotTypes[snapshot.type],
    }

    if (snapshot.type === EventType.IncrementalSnapshot) {
        snapshotSummary['source'] = incrementalSource[snapshot.data.source]
    }

    return (
        <div>
            <JSONViewer src={snapshotSummary} />
            <LemonButton onClick={() => setOpen(!open)}>Show snapshot</LemonButton>
            {open && <JSONViewer src={snapshot} />}
        </div>
    )
}
