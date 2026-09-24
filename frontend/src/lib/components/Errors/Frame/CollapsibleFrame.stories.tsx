import type { Meta } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingStackFrame, ErrorTrackingStackFrameContext, ErrorTrackingStackFrameRecord } from '../types'
import { CollapsibleFrame, CollapsibleFrameProps } from './CollapsibleFrame'

const frameContext: ErrorTrackingStackFrameContext = {
    before: [
        { number: 6, line: 'type RetryPolicy = { maxRetries: number; enabled: boolean }' },
        { number: 7, line: 'const DEFAULT_POLICY: RetryPolicy = { maxRetries: 3, enabled: true }' },
        { number: 8, line: '// Keep retries bounded before surfacing the error' },
        { number: 9, line: 'class FrameLoader {' },
        { number: 10, line: '    @trace({ category: "frames" })' },
    ],
    line: { number: 11, line: '    async loadFrameContexts(policy: RetryPolicy | null): Promise<void> {' },
    after: [
        {
            number: 12,
            line: '        await loadFrames(policy?.maxRetries ?? DEFAULT_POLICY.maxRetries)',
        },
        { number: 13, line: '    }' },
        { number: 14, line: '}' },
    ],
}

const baseFrame: ErrorTrackingStackFrame = {
    raw_id: 'frame-1',
    mangled_name: 'loadFrameContexts',
    line: 11,
    column: 5,
    source: 'src/lib/components/Errors/FrameLoader.ts',
    in_app: true,
    resolved_name: 'loadFrameContexts',
    lang: 'typescript',
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

const meta: Meta<CollapsibleFrameProps> = {
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
InitiallyExpanded.parameters = { testOptions: { skipDarkMode: true } }

export function InitiallyExpandedDark(): JSX.Element {
    return <Wrapper frame={baseFrame} record={baseRecord} initialExpanded />
}
InitiallyExpandedDark.globals = { theme: 'dark' }
InitiallyExpandedDark.parameters = {
    testOptions: { skipLightMode: true, waitForSelector: "[theme='dark'] .hljs" },
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

const addressOnlyFrame: ErrorTrackingStackFrame = {
    raw_id: 'address-only-1',
    mangled_name: '',
    line: null,
    column: null,
    source: null,
    in_app: false,
    resolved_name: null,
    lang: 'swift',
    resolved: false,
    resolve_failure: 'No matching debug image found for frame',
    module: null,
    junk_drawer: { raw_frame: { instruction_addr: '0x00000001010444e4' } },
}

export function AddressOnlyFrame(): JSX.Element {
    return <Wrapper frame={addressOnlyFrame} />
}

export function AddressOnlyInAppFrame(): JSX.Element {
    return <Wrapper frame={{ ...addressOnlyFrame, raw_id: 'address-only-2', in_app: true }} />
}

export function FrameWithNothingToShow(): JSX.Element {
    return <Wrapper frame={{ ...addressOnlyFrame, raw_id: 'nothing-1', junk_drawer: undefined }} />
}

const rustFrame: ErrorTrackingStackFrame = {
    ...baseFrame,
    raw_id: 'rust-1',
    mangled_name: '_ZN7example4main17h5c8e...',
    resolved_name: 'load_frames',
    source: 'src/main.rs',
    line: 12,
    column: 5,
    lang: 'rust',
}

const rustRecord: ErrorTrackingStackFrameRecord = {
    ...baseRecord,
    raw_id: 'rust-1',
    context: {
        before: [
            { number: 9, line: 'struct RetryPolicy { max_retries: usize }' },
            { number: 10, line: 'const DEFAULT_RETRIES: Option<usize> = None;' },
            { number: 11, line: '#[instrument(fields(category = "frames"))]' },
        ],
        line: { number: 12, line: 'fn load_frames(policy: &RetryPolicy) -> Result<Vec<Frame>, Error> {' },
        after: [
            { number: 13, line: '    // Keep retries bounded before surfacing the error' },
            { number: 14, line: '    client.load(policy.max_retries).expect("frames should load")' },
            { number: 15, line: '}' },
        ],
    },
}

export function RustFrameWithContext(): JSX.Element {
    return <Wrapper frame={rustFrame} record={rustRecord} initialExpanded />
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

const repoFrame: ErrorTrackingStackFrame = { ...baseFrame, raw_id: 'repo-1', repo_path: 'apps/web/src/FrameLoader.ts' }

const sourceFileLines = [
    ...Array.from({ length: 5 }, (_, i) => `// FrameLoader.ts line ${i + 1}`),
    ...frameContext.before.map(({ line }) => line),
    frameContext.line.line,
    ...frameContext.after.map(({ line }) => line),
    ...Array.from({ length: 40 }, (_, i) => `// FrameLoader.ts line ${i + 15}`),
]

export function SourceFileFromRepository(): JSX.Element {
    const properties = {
        ...eventProperties,
        $exception_release: {
            id: 'release-1',
            version: '1.0.0',
            timestamp: '2024-01-01T00:00:00Z',
            metadata: {
                git: {
                    remote_url: 'https://github.com/acme/web.git',
                    commit_id: '0123456789abcdef0123456789abcdef01234567',
                },
            },
        },
    }
    return (
        <BindLogic
            logic={errorPropertiesLogic}
            props={{ properties, id: 'story-source-file', timestamp: '2024-01-01T00:00:00Z' }}
        >
            <div className="max-w-2xl border rounded">
                <CollapsibleFrame
                    frame={repoFrame}
                    record={{ ...baseRecord, raw_id: 'repo-1', contents: repoFrame }}
                    recordLoading={false}
                    expanded
                    onExpandedChange={() => {}}
                />
            </div>
        </BindLogic>
    )
}
SourceFileFromRepository.decorators = [
    mswDecorator({
        get: {
            '/api/projects/:team_id/error_tracking/git-provider-file-links/source_file/': {
                repo_path: 'apps/web/src/FrameLoader.ts',
                commit: '0123456789abcdef0123456789abcdef01234567',
                line: 11,
                lines: sourceFileLines,
            },
        },
    }),
]
SourceFileFromRepository.parameters = {
    testOptions: { waitForSelector: '[data-attr="error-tracking-frame-source-file"]' },
}
