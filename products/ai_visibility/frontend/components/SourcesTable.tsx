import { LemonTable, Link } from '@posthog/lemon-ui'

import { SourceDetails } from '../types'

export function SourcesTable({ sources, brandName }: { sources: SourceDetails[]; brandName: string }): JSX.Element {
    return (
        <LemonTable
            dataSource={sources}
            columns={[
                {
                    title: 'Domain',
                    dataIndex: 'domain',
                    render: (_, source) => (
                        <div className="flex items-center gap-2">
                            <img
                                src={`https://www.google.com/s2/favicons?domain=${source.domain}&sz=128`}
                                alt=""
                                className="w-5 h-5"
                            />
                            <Link to={`https://${source.domain}`} target="_blank">
                                {source.domain}
                            </Link>
                        </div>
                    ),
                },
                {
                    title: 'Pages',
                    dataIndex: 'pages',
                    align: 'right',
                    sorter: (a, b) => a.pages - b.pages,
                },
                {
                    title: 'Responses',
                    dataIndex: 'responses',
                    align: 'right',
                    sorter: (a, b) => a.responses - b.responses,
                },
                {
                    title: `${brandName} Mention Rate`,
                    dataIndex: 'brandMentionRate',
                    align: 'right',
                    sorter: (a, b) => a.brandMentionRate - b.brandMentionRate,
                    render: (rate) => `${rate}%`,
                },
            ]}
            defaultSorting={{ columnKey: 'responses', order: -1 }}
        />
    )
}
