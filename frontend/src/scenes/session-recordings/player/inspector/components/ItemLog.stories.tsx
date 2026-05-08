import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { dayjs } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { uuid } from 'lib/utils'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { mswDecorator } from '~/mocks/browser'
import { LogMessage, LogSeverityLevel } from '~/queries/schema/schema-general'

import { InspectorListItemLog } from '../playerInspectorLogic'
import { ItemLog, ItemLogDetail, ItemLogProps } from './ItemLog'

type Story = StoryObj<ItemLogProps>
const meta: Meta<ItemLogProps> = {
    title: 'Components/PlayerInspector/ItemLog',
    component: ItemLog,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

function makeLogMessage(overrides: Partial<LogMessage> = {}): LogMessage {
    return {
        uuid: uuid(),
        trace_id: 'abc123def456',
        span_id: 'span-001',
        body: 'Processing request for /api/users',
        attributes: {
            'http.method': 'GET',
            'http.url': '/api/users',
            'http.status_code': '200',
        },
        timestamp: dayjs('2025-01-15T10:30:00Z').toISOString(),
        observed_timestamp: dayjs('2025-01-15T10:30:00Z').toISOString(),
        severity_text: 'info',
        severity_number: 9,
        level: 'info',
        resource_attributes: { 'service.name': 'api-server' },
        instrumentation_scope: 'api-server',
        event_name: '',
        ...overrides,
    }
}

function makeItem(
    level: LogSeverityLevel,
    body: string,
    overrides: Partial<LogMessage> = {},
    itemOverrides: Partial<InspectorListItemLog> = {}
): InspectorListItemLog {
    const mockDate = dayjs('2025-01-15T10:30:00Z')
    const highlightColor = level === 'error' || level === 'fatal' ? 'danger' : level === 'warn' ? 'warning' : undefined

    return {
        type: 'logs',
        timestamp: mockDate,
        timeInRecording: 5000,
        search: body,
        key: `log-${uuid()}`,
        highlightColor,
        data: makeLogMessage({ level, severity_text: level, body, ...overrides }),
        ...itemOverrides,
    }
}

const renderBasic = (props: Partial<ItemLogProps>): JSX.Element => {
    const propsToUse = {
        item: makeItem('info', 'Processing request for /api/users'),
        ...props,
    } as ItemLogProps

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={{ sessionRecordingId: '12345' }}>
            <div className="flex flex-col gap-2 min-w-96">
                <h3>Collapsed</h3>
                <ItemLog {...propsToUse} />
                <LemonDivider />
                <h3>Expanded</h3>
                <ItemLogDetail {...propsToUse} />
                <LemonDivider />
                <h3>Collapsed with overflowing text</h3>
                <div className="w-20">
                    <ItemLog {...propsToUse} />
                </div>
            </div>
        </BindLogic>
    )
}

export const InfoLog: Story = {
    render: renderBasic as any,
    args: {
        item: makeItem('info', 'User authentication successful for user_id=12345'),
    },
}

export const WarnLog: Story = {
    render: renderBasic as any,
    args: {
        item: makeItem('warn', 'Rate limit approaching: 95% of quota used for api-key=sk_***abc', {
            attributes: {
                api_key: 'sk_***abc',
                usage_percent: '95',
                limit: '1000',
            },
        }),
    },
}

export const ErrorLog: Story = {
    render: renderBasic as any,
    args: {
        item: makeItem('error', 'Failed to connect to database: connection timeout after 30s', {
            attributes: {
                'db.system': 'postgresql',
                'db.host': 'db-primary.internal',
                'error.type': 'ConnectionTimeoutError',
                retry_count: '3',
            },
            instrumentation_scope: 'database-pool',
        }),
    },
}

export const FatalLog: Story = {
    render: renderBasic as any,
    args: {
        item: makeItem('fatal', 'Out of memory: heap allocation failed, shutting down', {
            attributes: {
                'process.memory_used': '4096MB',
                'process.memory_limit': '4096MB',
                'os.type': 'linux',
            },
            instrumentation_scope: 'process-monitor',
        }),
    },
}

export const DebugLog: Story = {
    render: renderBasic as any,
    args: {
        item: makeItem('debug', 'Cache miss for key: user_prefs_12345, fetching from source', {
            attributes: {
                'cache.key': 'user_prefs_12345',
                'cache.backend': 'redis',
            },
            instrumentation_scope: 'cache-service',
        }),
    },
}

export const TraceLog: Story = {
    render: renderBasic as any,
    args: {
        item: makeItem('trace', 'Entering middleware: auth_check', {
            attributes: {},
            instrumentation_scope: 'middleware',
        }),
    },
}

export const LogWithNoAttributes: Story = {
    render: renderBasic as any,
    args: {
        item: makeItem('info', 'Simple log message with no extra attributes', {
            attributes: {},
            instrumentation_scope: '',
        }),
    },
}

export const LogWithLongBody: Story = {
    render: (props: Partial<ItemLogProps>) => {
        const propsToUse = {
            item: makeItem(
                'info',
                'This is a very long log message that contains a lot of information about what happened during the request processing pipeline including multiple stages of validation, transformation, and storage operations that were performed on the incoming data payload before it was finally committed to the database and a response was sent back to the client',
                {
                    attributes: {
                        'request.id': 'req-abc-123-def-456',
                        'request.duration_ms': '1523',
                        'request.size_bytes': '45230',
                    },
                }
            ),
            ...props,
        } as ItemLogProps

        return (
            <BindLogic logic={sessionRecordingPlayerLogic} props={{ sessionRecordingId: '12345' }}>
                <div className="flex flex-col gap-2 w-[400px]">
                    <h3>Collapsed (constrained width)</h3>
                    <ItemLog {...propsToUse} />
                    <LemonDivider />
                    <h3>Expanded (constrained width)</h3>
                    <ItemLogDetail {...propsToUse} />
                </div>
            </BindLogic>
        )
    },
    args: {},
}

export const LogWithGroupedItems: Story = {
    render: renderBasic as any,
    args: {
        item: makeItem('info', 'Health check passed'),
        groupCount: 5,
        groupedItems: Array.from({ length: 5 }, (_, i) =>
            makeItem('info', 'Health check passed', {}, { timeInRecording: 5000 + i * 10000, key: `grouped-${i}` })
        ),
    },
}

export const LogWithSessionId: Story = {
    render: renderBasic as any,
    args: {
        item: makeItem('info', 'Session event processed', {
            attributes: {
                session_id: '01900000-0000-0000-0000-000000000001',
                'user.id': 'user_12345',
            },
        }),
        sessionId: '01900000-0000-0000-0000-000000000001',
    },
}

export const ErrorLogWithBadge: Story = {
    render: renderBasic as any,
    args: {
        item: makeItem('error', 'Connection refused to upstream service'),
        groupCount: 42,
    },
}

export const AllSeverityLevels: Story = {
    render: () => {
        const levels: { level: LogSeverityLevel; body: string }[] = [
            { level: 'trace', body: 'Entering function processPayment()' },
            { level: 'debug', body: 'Cache lookup for key: session_abc123' },
            { level: 'info', body: 'User login successful for user@example.com' },
            { level: 'warn', body: 'Deprecated API endpoint called: /v1/users' },
            { level: 'error', body: 'Failed to send email: SMTP connection refused' },
            { level: 'fatal', body: 'Unrecoverable error: data corruption detected in partition 3' },
        ]

        return (
            <BindLogic logic={sessionRecordingPlayerLogic} props={{ sessionRecordingId: '12345' }}>
                <div className="flex flex-col gap-2 min-w-96">
                    <h3>All severity levels</h3>
                    {levels.map(({ level, body }) => (
                        <div key={level} className="border rounded">
                            <ItemLog item={makeItem(level, body)} />
                        </div>
                    ))}
                    <LemonDivider />
                    <h3>All severity levels expanded</h3>
                    {levels.map(({ level, body }) => (
                        <div key={level} className="border rounded">
                            <ItemLog item={makeItem(level, body)} />
                            <ItemLogDetail
                                item={makeItem(level, body, {
                                    instrumentation_scope: 'example-service',
                                    attributes: { environment: 'production', 'service.version': '2.1.0' },
                                })}
                            />
                        </div>
                    ))}
                </div>
            </BindLogic>
        )
    },
}
