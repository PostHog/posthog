import { LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel } from '~/types'

export const VARIABLE_INSIGHT_COLUMNS: LemonTableColumns<QueryBasedInsightModel> = [
    {
        title: 'Name',
        dataIndex: 'name',
        key: 'name',
        render: function renderName(name: string, insight) {
            return (
                <LemonTableLink
                    to={urls.insightView(insight.short_id)}
                    title={name || <i>Untitled</i>}
                    description={insight.description}
                />
            )
        },
    },
    {
        title: 'Created',
        dataIndex: 'created_at',
        render: function RenderCreated(created_at: string) {
            return created_at ? (
                <div className="whitespace-nowrap text-right">
                    <TZLabel time={created_at} />
                </div>
            ) : (
                <span className="text-secondary">—</span>
            )
        },
        align: 'right',
    },
    {
        title: 'Last modified',
        dataIndex: 'last_modified_at',
        render: function renderLastModified(last_modified_at: string) {
            return <div className="whitespace-nowrap">{last_modified_at && <TZLabel time={last_modified_at} />}</div>
        },
    },
    {
        title: 'Last viewed',
        dataIndex: 'last_viewed_at',
        render: function renderLastViewed(last_viewed_at: string | null) {
            return (
                <div className="whitespace-nowrap">
                    {last_viewed_at ? <TZLabel time={last_viewed_at} /> : <span className="text-muted">Never</span>}
                </div>
            )
        },
    },
]
