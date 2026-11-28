import { router } from 'kea-router'

import { Button } from '@posthog/quill'

import { urls } from 'scenes/urls'

const ISSUES = [
    { name: "TypeError: Cannot read properties of undefined (reading 'id')", occurrences: 1284, users: 312 },
    { name: 'ChunkLoadError: Loading chunk 42 failed', occurrences: 640, users: 201 },
    { name: 'RangeError: Maximum call stack size exceeded', occurrences: 87, users: 19 },
]

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product renders its own custom content in a dashboard.
export function TopIssuesList(): JSX.Element {
    return (
        <div className="flex h-full flex-col gap-1">
            {ISSUES.map(({ name, occurrences, users }) => (
                <div key={name} className="flex items-center justify-between gap-4 py-1">
                    <span className="truncate">{name}</span>
                    <span className="shrink-0 text-secondary tabular-nums">
                        {occurrences.toLocaleString()} times · {users} people
                    </span>
                </div>
            ))}
            <Button
                variant="outline"
                size="sm"
                className="mt-auto self-start"
                data-attr="dashboard-v2-example-view-issues"
                onClick={() => router.actions.push(urls.errorTracking())}
            >
                View all issues
            </Button>
        </div>
    )
}
