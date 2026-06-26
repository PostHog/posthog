import type { LogsWidgetLogLine } from './LogsWidgetRow'

/** Static sample log lines for previews and Storybook (no network). */
export const logsWidgetSampleLogLines: LogsWidgetLogLine[] = [
    {
        uuid: 'log-1',
        timestamp: '2026-05-26T08:04:10.000Z',
        severity_text: 'error',
        level: 'error',
        body: 'Unhandled exception while processing checkout: payment gateway timeout',
        trace_id: 'abc123',
    },
    {
        uuid: 'log-2',
        timestamp: '2026-05-26T08:04:05.000Z',
        severity_text: 'warn',
        level: 'warn',
        body: 'Retrying request to billing-service (attempt 2/3)',
        trace_id: 'abc124',
    },
    {
        uuid: 'log-3',
        timestamp: '2026-05-26T08:04:01.000Z',
        severity_text: 'info',
        level: 'info',
        body: 'User session started for distinct_id=user-42',
        trace_id: 'abc125',
    },
    {
        uuid: 'log-4',
        timestamp: '2026-05-26T08:03:58.000Z',
        severity_text: 'info',
        level: 'info',
        body: 'GET /api/projects/2/dashboards 200 in 84ms',
        trace_id: 'abc126',
    },
    {
        uuid: 'log-5',
        timestamp: '2026-05-26T08:03:50.000Z',
        severity_text: 'debug',
        level: 'debug',
        body: 'Cache miss for key dashboard:2:tiles, recomputing',
        trace_id: 'abc127',
    },
]
