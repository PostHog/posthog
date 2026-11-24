import { useValues } from 'kea'

import { urls } from 'scenes/urls'

import { EntityListHost } from '../lists/EntityListHost'
import { withFacets } from '../lists/facetFilters'
import { TraceListRow } from '../trace/traceListRows'
import { peopleTableColumns } from './components/peopleTableColumns'
import { PersonDetail } from './components/PersonDetail'
import { PEOPLE_LIST_FILTERS, peopleListLogic } from './peopleListLogic'
import { PersonRow, PersonTrace } from './peopleQueries'
import { personLabel } from './personLabel'

function toTraceRow(trace: PersonTrace): TraceListRow {
    return { traceId: trace.traceId, timestamp: trace.timestamp, stepId: null }
}

export function PeopleListHost(): JSX.Element {
    const { rows } = useValues(peopleListLogic)

    return (
        <EntityListHost
            logic={peopleListLogic}
            filters={{ ...PEOPLE_LIST_FILTERS, listId: 'people' }}
            columns={peopleTableColumns}
            rowKey={(row: PersonRow) => row.distinctId}
            searchPlaceholder="Search people"
            facetControls={['model', 'provider', 'tool', 'errors', 'slow']}
            noun="person"
            drawerTitle={(distinctId) => {
                const row = rows?.find((candidate) => candidate.distinctId === distinctId)
                return <span className="ph-no-capture">{row ? personLabel(row) : distinctId}</span>
            }}
            traceRows={(_, detail) => detail.traces.map(toTraceRow)}
            renderDetail={({ key, detail, labels, openTraceId, openTrace, propertyFilters, setPropertyFilters }) => (
                <PersonDetail
                    detail={detail}
                    labels={labels}
                    personHref={urls.personByDistinctId(key)}
                    activeTraceId={openTraceId}
                    onOpenTrace={(trace) => openTrace(toTraceRow(trace))}
                    onFilterModel={(model) =>
                        setPropertyFilters(withFacets(propertyFilters, { models: [model] }, null))
                    }
                    onFilterTool={(tool) => setPropertyFilters(withFacets(propertyFilters, { tools: [tool] }, null))}
                />
            )}
            emptyState={{
                title: 'No people in this date range',
                description:
                    'No generations came from an identified person. Pick a wider date range to check older events.',
            }}
            emptyFilteredTitle="No people match"
            errorTitle="Could not load people"
            // pinned: autocapture dashboards select the list and its controls by this value and the suffixes built on it
            data-attr="ai-observability-people-list"
        />
    )
}
