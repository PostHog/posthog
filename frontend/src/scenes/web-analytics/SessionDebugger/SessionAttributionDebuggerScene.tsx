import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, HogQLQuery } from '~/queries/schema'
import { isSessionPropertyFilters } from '~/queries/schema-guards'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'

import { sessionAttributionDebuggerLogic } from './sessionAttributionDebuggerLogic'

export function SessionAttributionDebuggerScene(): JSX.Element {
    return <SessionAttributionDebugger />
}

export const scene: SceneExport = {
    component: SessionAttributionDebuggerScene,
    logic: sessionAttributionDebuggerLogic,
}

const ExampleUrlsCell: QueryContextColumnComponent = ({ value }: { value: unknown }): JSX.Element => {
    const values = Array.isArray(value) ? value : [value]
    return (
        <div>
            {values.map((url) => (
                <div key={url}>{url}</div>
            ))}
        </div>
    )
}

const queryContext: QueryContext = {
    columns: {
        channel_type: {
            title: 'Channel type',
        },
        count: {
            title: 'Session count',
        },
        referring_domain: {
            title: 'Referring domain',
        },
        utm_source: {
            title: 'UTM source',
        },
        utm_medium: {
            title: 'UTM medium',
        },
        utm_campaign: {
            title: 'UTM campaign',
        },
        has_ad_id: {
            title: 'Has ad ID',
        },
        example_entry_urls: {
            title: 'Example entry URLs',
            render: ExampleUrlsCell,
        },
    },
}

export function SessionAttributionDebugger(): JSX.Element {
    const { query } = useValues(sessionAttributionDebuggerLogic)
    const { setFilters } = useActions(sessionAttributionDebuggerLogic)
    return (
        <div>
            <Query<DataTableNode>
                context={queryContext}
                query={query}
                setQuery={(query) => {
                    const source = query.source as HogQLQuery
                    if (source.filters?.properties && isSessionPropertyFilters(source.filters.properties)) {
                        setFilters(source.filters.properties)
                    }
                }}
            />
        </div>
    )
}
