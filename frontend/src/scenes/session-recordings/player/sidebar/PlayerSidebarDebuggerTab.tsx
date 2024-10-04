import { LemonButton, LemonCollapse, LemonInputSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { JSONViewer } from 'lib/components/JSONViewer'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { useEffect, useState } from 'react'
import { EventType, eventWithTime, IncrementalSource } from 'rrweb'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

const snapshotTypes: Record<EventType, string> = {
    [EventType.DomContentLoaded]: 'DomContentLoaded',
    [EventType.Load]: 'Load',
    [EventType.FullSnapshot]: 'FullSnapshot',
    [EventType.IncrementalSnapshot]: 'IncrementalSnapshot',
    [EventType.Meta]: 'Meta',
    [EventType.Custom]: 'Custom',
    [EventType.Plugin]: 'Plugin',
}

const incrementalSource = {
    [IncrementalSource.Mutation]: 'Mutation',
    [IncrementalSource.MouseMove]: 'MouseMove',
    [IncrementalSource.MouseInteraction]: 'MouseInteraction',
    [IncrementalSource.Scroll]: 'Scroll',
    [IncrementalSource.ViewportResize]: 'ViewportResize',
    [IncrementalSource.Input]: 'Input',
    [IncrementalSource.TouchMove]: 'TouchMove',
    [IncrementalSource.MediaInteraction]: 'MediaInteraction',
    [IncrementalSource.StyleSheetRule]: 'StyleSheetRule',
    [IncrementalSource.CanvasMutation]: 'CanvasMutation',
    [IncrementalSource.Font]: 'Font',
    [IncrementalSource.Log]: 'Log',
    [IncrementalSource.Drag]: 'Drag',
    [IncrementalSource.StyleDeclaration]: 'StyleDeclaration',
    [IncrementalSource.Selection]: 'Selection',
    [IncrementalSource.AdoptedStyleSheet]: 'AdoptedStyleSheet',
    [IncrementalSource.CustomElement]: 'CustomElement',
}

export function PlayerSidebarDebuggerTab(): JSX.Element {
    const { debugSnapshots, currentTimestamp, debugSettings } = useValues(sessionRecordingPlayerLogic)
    const { setPause, seekToTimestamp, setDebugSnapshotTypes, setDebugSnapshotIncrementalSources } =
        useActions(sessionRecordingPlayerLogic)

    useEffect(() => {
        setPause()
    })

    const onClick = (snapshot: eventWithTime | null): void => {
        if (snapshot) {
            seekToTimestamp(snapshot.timestamp)
        }
    }

    const nextIndex = debugSnapshots.findIndex((s) => s.timestamp > (currentTimestamp || 0))
    const currentIndex = nextIndex - 1

    const previous = nextIndex === 0 ? null : debugSnapshots[nextIndex - 2]
    const current = nextIndex === 0 ? null : debugSnapshots[currentIndex]
    const next = nextIndex === -1 ? null : debugSnapshots[nextIndex]

    const typeValues = debugSettings.types.map((t) => t.toString())
    const sourceValues = debugSettings.incrementalSources.map((t) => t.toString())

    return (
        <div className="h-full bg-bg-3000 overflow-auto">
            <div className="p-2 flex gap-1">
                <LemonInputSelect
                    size="xsmall"
                    value={typeValues}
                    mode="multiple"
                    allowCustomValues={false}
                    onChange={(newVal) => {
                        setDebugSnapshotTypes(newVal.map((v) => parseInt(v)) as unknown as EventType[])
                    }}
                    options={Object.entries(snapshotTypes).map(([key, value]) => ({
                        key: key,
                        label: value,
                    }))}
                    placeholder="Choose snapshot types"
                />
                <LemonInputSelect
                    size="xsmall"
                    disabled={!debugSettings.types.includes(EventType.IncrementalSnapshot)}
                    value={sourceValues}
                    mode="multiple"
                    allowCustomValues={false}
                    onChange={(newVal) =>
                        setDebugSnapshotIncrementalSources(
                            newVal.map((v) => parseInt(v)) as unknown as IncrementalSource[]
                        )
                    }
                    options={Object.entries(incrementalSource).map(([key, value]) => ({
                        key: key,
                        label: value,
                    }))}
                    placeholder="Choose mutation types"
                />
            </div>

            <div className="p-2 flex gap-2 items-center">
                <LemonSlider
                    className="flex-1"
                    min={0}
                    max={debugSnapshots.length - 1}
                    value={currentIndex}
                    onChange={(v) => {
                        seekToTimestamp(debugSnapshots[v].timestamp)
                    }}
                />
                {Math.max(0, currentIndex)} / {debugSnapshots.length - 1}
            </div>
            <div className="p-2 flex gap-1 justify-between">
                <LemonButton
                    onClick={() => onClick(previous)}
                    icon={<IconChevronLeft />}
                    disabledReason={!previous ? "You're on the first snapshot" : null}
                    type="secondary"
                    size="small"
                >
                    Previous
                </LemonButton>
                <LemonButton
                    onClick={() => onClick(next)}
                    icon={<IconChevronRight />}
                    disabledReason={!next ? "You're on the last snapshot" : null}
                    type="secondary"
                    size="small"
                >
                    Next
                </LemonButton>
            </div>

            <div className="border-y">
                <LemonCollapse
                    size="xsmall"
                    defaultActiveKeys={['current', 'next']}
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
        if (snapshot.data.source === IncrementalSource.Mutation) {
            snapshotSummary['adds'] = snapshot.data.adds.length
            snapshotSummary['removes'] = snapshot.data.removes.length
        }
    }

    return (
        <div>
            <JSONViewer src={snapshotSummary} name="summary" />
            <LemonButton type="secondary" onClick={() => setOpen(!open)}>
                {open ? 'Hide' : 'Show'} snapshot
            </LemonButton>
            {open && <JSONViewer src={snapshot} name="snapshot" />}
        </div>
    )
}
