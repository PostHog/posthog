import { useActions, useValues } from 'kea'
import { eventsSceneLogic } from 'scenes/events/eventsSceneLogic'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { defaultDataTableStringColumns } from '~/queries/nodes/DataTable/DataTable'
import { isDataTableNode } from '~/queries/utils'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { teamLogic } from 'scenes/teamLogic'
import { LemonTableConfig } from 'lib/components/ResizableTable/TableConfig'

export function EventsScene(): JSX.Element {
    const { properties, eventFilter } = useValues(eventsSceneLogic)
    const { setProperties, setEventFilter } = useActions(eventsSceneLogic)
    const { currentTeam } = useValues(teamLogic)
    const { selectedColumns } = useValues(
        tableConfigLogic({
            startingColumns: (currentTeam && currentTeam.live_events_columns) ?? [],
        })
    )

    const columns =
        !selectedColumns || selectedColumns === 'DEFAULT' || selectedColumns.length === 0
            ? defaultDataTableStringColumns
            : ['event', 'person', ...selectedColumns.map((c) => `properties.${c}`), 'timestamp']

    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        columns,
        source: {
            kind: NodeKind.EventsNode,
            properties: properties,
            event: eventFilter,
            limit: 100,
        },
    }
    return (
        <>
            <LemonTableConfig immutableColumns={['event', 'person']} defaultColumns={query.columns as string[]} />
            <Query
                query={query}
                setQuery={(query) => {
                    if (isDataTableNode(query)) {
                        setProperties(query.source.properties ?? [])
                        setEventFilter(query.source.event ?? '')
                    }
                }}
            />
        </>
    )
}
