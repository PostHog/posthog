import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { catalogMetricWorksheet } from './biCatalog'
import { biCatalogPickerLogic } from './biCatalogPickerLogic'

export function BICatalogMetricPicker(): JSX.Element {
    const { isOpen, search, page, metrics, metricsLoading, error } = useValues(biCatalogPickerLogic)
    const { open, close, setSearch, setPage, loadMetrics } = useActions(biCatalogPickerLogic)
    return (
        <>
            <LemonButton type="secondary" size="small" onClick={open}>
                Use a catalog metric
            </LemonButton>
            <LemonModal isOpen={isOpen} onClose={close} title="Use a catalog metric" width={640}>
                <div className="flex flex-col gap-3">
                    <p className="m-0 text-secondary">
                        Open a SQL copy in a new worksheet. Catalog changes won't update the copy.
                    </p>
                    <LemonInput
                        type="search"
                        aria-label="Search catalog metrics"
                        placeholder="Search catalog metrics"
                        value={search}
                        onChange={setSearch}
                    />
                    {error ? (
                        <LemonBanner type="error">
                            Couldn't load catalog metrics.{' '}
                            <LemonButton size="xsmall" loading={metricsLoading} onClick={() => loadMetrics()}>
                                Retry
                            </LemonButton>
                        </LemonBanner>
                    ) : metricsLoading ? (
                        <Spinner />
                    ) : metrics?.results.length ? (
                        <div className="flex max-h-96 flex-col gap-3 overflow-y-auto">
                            {metrics.results.map((metric) => (
                                <div key={metric.id} className="flex min-w-0 flex-col gap-1 rounded border p-2">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span className="min-w-0 break-all font-semibold">
                                            {metric.display_name || metric.name}
                                        </span>
                                        <LemonTag
                                            type={
                                                metric.status === 'approved' && !metric.is_drifted
                                                    ? 'success'
                                                    : 'warning'
                                            }
                                        >
                                            {metric.is_drifted
                                                ? 'Drifted'
                                                : metric.status === 'approved'
                                                  ? 'Approved'
                                                  : 'Proposed'}
                                        </LemonTag>
                                    </div>
                                    <p className="m-0 break-words text-secondary">{metric.description}</p>
                                    <div className="flex flex-wrap gap-2">
                                        <LemonButton
                                            size="xsmall"
                                            type="primary"
                                            disabledReason={
                                                catalogMetricWorksheet(metric)
                                                    ? undefined
                                                    : 'BI supports SQL metric definitions. View this metric in the catalog.'
                                            }
                                            to={combineUrl(urls.businessIntelligenceNew(), { metric: metric.name }).url}
                                            onClick={close}
                                        >
                                            Open copy in BI
                                        </LemonButton>
                                        <LemonButton
                                            size="xsmall"
                                            to={urls.dataCatalogMetric(metric.name)}
                                            onClick={close}
                                        >
                                            View in catalog
                                        </LemonButton>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <p className="m-0 text-secondary">No catalog metrics found.</p>
                    )}
                    <div className="flex gap-2">
                        <LemonButton
                            size="small"
                            disabledReason={page === 0 || metricsLoading ? 'No previous page available' : undefined}
                            onClick={() => setPage(page - 1)}
                        >
                            Previous
                        </LemonButton>
                        <LemonButton
                            size="small"
                            disabledReason={
                                !metrics?.next || metricsLoading || error ? 'No next page available' : undefined
                            }
                            onClick={() => setPage(page + 1)}
                        >
                            Next
                        </LemonButton>
                    </div>
                </div>
            </LemonModal>
        </>
    )
}
