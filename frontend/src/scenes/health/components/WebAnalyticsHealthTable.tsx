import { Link } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import type { HealthIssue } from '../types'
import { dismissActionColumn, severityColumn } from './healthTableColumns'

interface CheckMeta {
    title: string
    description: string
    docsUrl?: string
    linkLabel?: string
}

const CHECK_META: Record<string, CheckMeta> = {
    no_live_events: {
        title: '$pageview',
        description: 'No pageview events detected recently. Complete the PostHog installation to start seeing events.',
        docsUrl: 'https://posthog.com/docs/product-analytics/capture-events',
    },
    no_pageleave_events: {
        title: '$pageleave',
        description: 'Without $pageleave events, bounce rate and session duration might be inaccurate.',
        docsUrl: 'https://posthog.com/docs/web-analytics/dashboard#bounce-rate',
    },
    scroll_depth: {
        title: 'Scroll depth',
        description: 'Enable scroll depth to see how far users read your content before leaving.',
        docsUrl: 'https://posthog.com/tutorials/scroll-depth',
    },
    authorized_urls: {
        title: 'Authorized URLs',
        description: "No authorized URLs configured. Some filters won't work correctly until you set your domains.",
        docsUrl: urls.settings('environment-web-analytics', 'web-analytics-authorized-urls'),
        linkLabel: 'Settings',
    },
    reverse_proxy: {
        title: 'Reverse proxy',
        description:
            'A reverse proxy routes requests through your domain and helps prevent ad blockers from blocking tracking.',
        docsUrl: 'https://posthog.com/docs/advanced/proxy',
    },
    web_vitals: {
        title: '$web_vitals',
        description:
            'Core Web Vitals (LCP, INP, CLS) measure real user experience. Google uses these metrics for search ranking.',
        docsUrl: 'https://posthog.com/docs/web-analytics/web-vitals',
    },
}

export function WebAnalyticsHealthTable({
    issues,
    onDismiss,
    onUndismiss,
}: {
    issues: HealthIssue[]
    onDismiss: (id: string) => void
    onUndismiss: (id: string) => void
}): JSX.Element {
    const columns: LemonTableColumns<HealthIssue> = [
        {
            title: 'Check',
            key: 'check',
            render: function Render(_, issue: HealthIssue) {
                const meta = CHECK_META[issue.kind]

                return (
                    <div className="py-1">
                        <div className="flex items-center gap-2">
                            {meta?.title.startsWith('$') ? (
                                <code className="font-medium text-sm bg-fill-primary px-1.5 py-0.5 rounded">
                                    {meta.title}
                                </code>
                            ) : (
                                <span className="font-medium">{meta?.title ?? issue.kind}</span>
                            )}
                            {meta?.docsUrl && (
                                <Link to={meta.docsUrl} className="text-xs text-muted">
                                    {meta.linkLabel ?? 'Docs'}
                                </Link>
                            )}
                        </div>
                        {meta?.description && <div className="text-xs text-muted mt-0.5">{meta.description}</div>}
                    </div>
                )
            },
        },
        severityColumn(),
        dismissActionColumn(onDismiss, onUndismiss),
    ]

    return <LemonTable dataSource={issues} columns={columns} embedded size="small" rowClassName="group" />
}
