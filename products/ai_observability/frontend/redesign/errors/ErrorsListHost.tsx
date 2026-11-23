import { EntityListHost } from '../lists/EntityListHost'
import { withFacets } from '../lists/facetFilters'
import { TraceListRow } from '../trace/traceListRows'
import { ErrorDetail } from './components/ErrorDetail'
import { errorsTableColumns } from './components/errorsTableColumns'
import { ERRORS_LIST_FILTERS, errorsListLogic } from './errorsListLogic'
import { ErrorExample, ErrorRow } from './errorsQueries'

function toTraceRow(example: ErrorExample, error: string): TraceListRow {
    return { traceId: example.traceId, timestamp: example.timestamp, stepId: example.uuid, label: error }
}

export function ErrorsListHost(): JSX.Element {
    return (
        <EntityListHost
            logic={errorsListLogic}
            filters={{ ...ERRORS_LIST_FILTERS, listId: 'errors' }}
            columns={errorsTableColumns}
            rowKey={(row: ErrorRow) => row.error}
            searchPlaceholder="Search errors"
            facetControls={['model', 'provider', 'tool', 'slow']}
            noun="error"
            drawerTitle={() => 'Error'}
            traceRows={(error, detail) => detail.examples.map((example) => toTraceRow(example, error))}
            renderDetail={({ key, detail, labels, openStepId, openTrace, propertyFilters, setPropertyFilters }) => (
                <ErrorDetail
                    error={key}
                    detail={detail}
                    labels={labels}
                    activeExampleKey={openStepId}
                    onOpenExample={(example) => openTrace(toTraceRow(example, key))}
                    onFilterModel={(model) =>
                        setPropertyFilters(withFacets(propertyFilters, { models: [model] }, null))
                    }
                />
            )}
            emptyState={{
                title: 'No errors in this date range',
                description: 'None of your AI events ended in an error. Pick a wider date range to check older events.',
            }}
            emptyFilteredTitle="No errors match"
            errorTitle="Could not load errors"
            // pinned: autocapture dashboards select the list and its controls by this value and the suffixes built on it
            data-attr="ai-observability-errors-list"
        />
    )
}
