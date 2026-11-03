import { useActions, useValues } from 'kea'

import { IconRefresh, IconSearch } from '@posthog/icons'
import { Button, InputGroup, InputGroupAddon, InputGroupInput } from '@posthog/quill'

import { reloadDisabledReason } from '../metricActionGuards'
import { metricsLogic } from '../metricsLogic'
import { CatalogMetricsFilterMenu } from './CatalogMetricsFilterMenu'

export function CatalogMetricsToolbar(): JSX.Element {
    const { filters, allMetricsLoading, actionsInFlight, bulkActionInFlight } = useValues(metricsLogic)
    const { setFilters, loadMetrics } = useActions(metricsLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup size="sm" className="w-full @min-[40rem]/main-content:w-72">
                <InputGroupAddon>
                    <IconSearch />
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    placeholder="Search metrics"
                    aria-label="Search metrics"
                    value={filters.search}
                    onChange={(event) => setFilters({ search: event.target.value })}
                    data-attr="data-catalog-metrics-search"
                />
            </InputGroup>
            <CatalogMetricsFilterMenu />
            <Button
                size="icon"
                aria-label="Reload metrics"
                tooltip="Reload metrics"
                className="ml-auto text-muted-foreground"
                loading={allMetricsLoading}
                disabledReason={reloadDisabledReason(bulkActionInFlight, actionsInFlight)}
                onClick={() => loadMetrics()}
                data-attr="data-catalog-metrics-reload"
            >
                <IconRefresh />
            </Button>
        </div>
    )
}
