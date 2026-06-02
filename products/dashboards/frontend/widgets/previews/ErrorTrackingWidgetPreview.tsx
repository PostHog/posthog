import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ErrorTrackingIssueList } from 'products/error_tracking/frontend/components/ErrorTrackingIssueList/ErrorTrackingIssueList'

const PREVIEW_ISSUES: ErrorTrackingIssue[] = [
    {
        id: 'preview-1',
        name: 'Checkout API timeout',
        description:
            'Checkout requests occasionally time out while creating a payment session, preventing upgrades from completing.',
        function: 'fetch',
        source: 'https://app.hedgebox.test/static/js/api.js',
        library: 'web',
        status: 'active',
        assignee: null,
        first_seen: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
        last_seen: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
        aggregations: {
            occurrences: 42,
            sessions: 18,
            users: 12,
            volume_buckets: [
                { label: new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString(), value: 2 },
                { label: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(), value: 4 },
                { label: new Date(Date.now() - 4 * 24 * 60 * 60 * 1000).toISOString(), value: 3 },
                { label: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(), value: 8 },
                { label: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(), value: 12 },
                { label: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(), value: 6 },
                { label: new Date().toISOString(), value: 4 },
            ],
        },
    },
    {
        id: 'preview-2',
        name: 'File preview render failure',
        description:
            'Preview rendering fails for some uploaded PDFs, leaving customers unable to inspect files before sharing them.',
        function: 'renderPreview',
        source: 'https://app.hedgebox.test/static/js/workers/pdf.js',
        library: 'web',
        status: 'active',
        assignee: null,
        first_seen: new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString(),
        last_seen: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
        aggregations: {
            occurrences: 18,
            sessions: 9,
            users: 7,
            volume_buckets: [
                { label: new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString(), value: 1 },
                { label: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(), value: 1 },
                { label: new Date(Date.now() - 4 * 24 * 60 * 60 * 1000).toISOString(), value: 2 },
                { label: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(), value: 3 },
                { label: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(), value: 2 },
                { label: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(), value: 1 },
                { label: new Date().toISOString(), value: 1 },
            ],
        },
    },
    {
        id: 'preview-3',
        name: 'TypeError: Cannot read properties of undefined',
        description: 'User profile settings fail to load when the session cache is empty.',
        function: 'loadProfile',
        source: 'https://app.hedgebox.test/static/js/settings.js',
        library: 'web',
        status: 'pending_release',
        assignee: null,
        first_seen: new Date(Date.now() - 21 * 24 * 60 * 60 * 1000).toISOString(),
        last_seen: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
        aggregations: {
            occurrences: 9,
            sessions: 4,
            users: 3,
            volume_buckets: [
                { label: new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString(), value: 0 },
                { label: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(), value: 1 },
                { label: new Date(Date.now() - 4 * 24 * 60 * 60 * 1000).toISOString(), value: 0 },
                { label: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(), value: 2 },
                { label: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(), value: 1 },
                { label: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(), value: 0 },
                { label: new Date().toISOString(), value: 0 },
            ],
        },
    },
]

export function ErrorTrackingWidgetPreview(): JSX.Element {
    return (
        <div className="pointer-events-none shadow-sm">
            <ErrorTrackingIssueList issues={PREVIEW_ISSUES} />
        </div>
    )
}
