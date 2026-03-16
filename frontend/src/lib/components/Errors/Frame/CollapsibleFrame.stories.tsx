import type { Meta } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameContext, ErrorTrackingStackFrameRecord } from '../types'
import { CollapsibleFrame } from './CollapsibleFrame'

const frameContext: ErrorTrackingStackFrameContext = {
    before: [
        { number: 7, line: '    const displayFrames = showAllFrames ? frames : frames.filter((f) => f.in_app)' },
        { number: 8, line: '' },
        { number: 9, line: '    useEffect(() => {' },
    ],
    line: { number: 10, line: '        loadFrameContexts({ frames })' },
    after: [
        { number: 11, line: '    }, [frames, loadFrameContexts])' },
        { number: 12, line: '' },
        { number: 13, line: '    const initiallyActiveIndex = displayFrames.findIndex((f) => f.in_app) || 0' },
    ],
}

const baseFrame: ErrorTrackingStackFrame = {
    raw_id: 'frame-1',
    mangled_name: 'loadFrameContexts',
    line: 10,
    column: 8,
    source: 'src/lib/components/Errors/ErrorDisplay.tsx',
    in_app: true,
    resolved_name: 'loadFrameContexts',
    lang: 'javascript',
    resolved: true,
    resolve_failure: null,
    module: null,
}

const baseRecord: ErrorTrackingStackFrameRecord = {
    id: 'record-1',
    raw_id: 'frame-1',
    created_at: '2024-01-01T00:00:00Z',
    resolved: true,
    context: frameContext,
    contents: baseFrame,
    symbol_set_ref: 'https://static.example.com/chunks.js',
    release: null,
}

const eventProperties = {
    $exception_list: [
        {
            type: 'Error',
            value: 'Something went wrong',
            stacktrace: {
                type: 'resolved' as const,
                frames: [baseFrame],
            },
        },
    ],
}

const meta: Meta<typeof CollapsibleFrame> = {
    title: 'Components/Errors/CollapsibleFrame',
    component: CollapsibleFrame,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/error_tracking/stack_frames/': {
                    results: [baseRecord],
                },
            },
        }),
    ],
}

export default meta

function Wrapper({
    frame,
    record,
    recordLoading = false,
    initialExpanded = false,
}: {
    frame: ErrorTrackingStackFrame
    record?: ErrorTrackingStackFrameRecord
    recordLoading?: boolean
    initialExpanded?: boolean
}): JSX.Element {
    const [expanded, setExpanded] = useState(initialExpanded)
    return (
        <BindLogic logic={errorPropertiesLogic} props={{ properties: eventProperties, id: 'story' }}>
            <div className="max-w-2xl border rounded">
                <CollapsibleFrame
                    frame={frame}
                    record={record}
                    recordLoading={recordLoading}
                    expanded={expanded}
                    onExpandedChange={setExpanded}
                />
            </div>
        </BindLogic>
    )
}

export function InAppWithContext(): JSX.Element {
    return <Wrapper frame={baseFrame} record={baseRecord} />
}

export function InitiallyExpanded(): JSX.Element {
    return <Wrapper frame={baseFrame} record={baseRecord} initialExpanded />
}

export function VendorFrame(): JSX.Element {
    return (
        <Wrapper
            frame={{
                ...baseFrame,
                raw_id: 'vendor-1',
                in_app: false,
                source: 'node_modules/react-dom/cjs/react-dom.development.js',
                resolved_name: 'commitWork',
            }}
            record={{ ...baseRecord, raw_id: 'vendor-1' }}
        />
    )
}

export function UnresolvedFrame(): JSX.Element {
    return (
        <Wrapper
            frame={{
                ...baseFrame,
                raw_id: 'unresolved-1',
                resolved: false,
                resolve_failure: 'No source map found for this frame',
            }}
        />
    )
}

export function NoContext(): JSX.Element {
    return <Wrapper frame={baseFrame} record={{ ...baseRecord, context: null }} />
}

export function Loading(): JSX.Element {
    return <Wrapper frame={baseFrame} recordLoading />
}

export function MultipleFrames(): JSX.Element {
    const frames: Array<{ frame: ErrorTrackingStackFrame; record?: ErrorTrackingStackFrameRecord }> = [
        {
            frame: {
                ...baseFrame,
                raw_id: 'f1',
                resolved_name: 'handleClick',
                source: 'src/components/Button.tsx',
                line: 42,
                column: 12,
            },
            record: { ...baseRecord, raw_id: 'f1' },
        },
        {
            frame: {
                ...baseFrame,
                raw_id: 'f2',
                resolved_name: 'dispatchEvent',
                source: 'src/lib/events.ts',
                line: 88,
                column: 4,
            },
            record: { ...baseRecord, raw_id: 'f2' },
        },
        {
            frame: {
                ...baseFrame,
                raw_id: 'f3',
                in_app: false,
                resolved_name: 'callCallback',
                source: 'node_modules/react-dom/cjs/react-dom.development.js',
                line: 4164,
            },
            record: { ...baseRecord, raw_id: 'f3' },
        },
        {
            frame: {
                ...baseFrame,
                raw_id: 'f4',
                resolved: false,
                resolve_failure: 'Missing source map',
                resolved_name: null,
                source: 'https://cdn.example.com/app.min.js',
                line: 1,
                column: 29384,
            },
        },
    ]

    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

    return (
        <BindLogic logic={errorPropertiesLogic} props={{ properties: eventProperties, id: 'story-multi' }}>
            <div className="max-w-2xl border rounded divide-y">
                {frames.map(({ frame, record }) => (
                    <CollapsibleFrame
                        key={frame.raw_id}
                        frame={frame}
                        record={record}
                        recordLoading={false}
                        expanded={expandedIds.has(frame.raw_id)}
                        onExpandedChange={(open) =>
                            setExpandedIds((prev) => {
                                const next = new Set(prev)
                                open ? next.add(frame.raw_id) : next.delete(frame.raw_id)
                                return next
                            })
                        }
                    />
                ))}
            </div>
        </BindLogic>
    )
}
