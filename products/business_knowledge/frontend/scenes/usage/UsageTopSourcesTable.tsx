import { LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { SourceUsageApi } from '../../generated/api.schemas'

export function UsageTopSourcesTable({ sources }: { sources: readonly SourceUsageApi[] }): JSX.Element {
    return (
        <LemonTable<SourceUsageApi>
            dataSource={[...sources]}
            rowKey={(row) => row.source_id}
            data-attr="business-knowledge-usage-top-sources"
            columns={[
                {
                    title: 'Source',
                    key: 'name',
                    render: (_, row) => (
                        <div className="flex min-w-0 items-center gap-2">
                            <Link to={urls.businessKnowledgeSource(row.source_id)} className="truncate">
                                {row.name}
                            </Link>
                            {row.is_generated ? <LemonTag>Learned</LemonTag> : null}
                        </div>
                    ),
                },
                {
                    title: 'Agent runs',
                    key: 'cited_run_count',
                    align: 'right',
                    render: (_, row) => row.cited_run_count.toLocaleString(),
                },
                {
                    title: 'Last cited',
                    key: 'last_cited_at',
                    render: (_, row) => <TZLabel time={row.last_cited_at} />,
                },
            ]}
        />
    )
}
