import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonDrawer, LemonInput, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import { MetricsQueryNode } from 'products/metrics/frontend/nodes/MetricsQueryNode'

import { MetricsPanelEditorProps, metricsPanelEditorLogic } from './metricsPanelEditorLogic'

export function MetricsPanelEditor(props: MetricsPanelEditorProps & { dashboardId?: number }): JSX.Element {
    const logic = metricsPanelEditorLogic(props)
    const { original, originalLoading, query, name, error, saving, dashboardCount, saveDisabledReason } =
        useValues(logic)
    const { setQuery, setName, save, requestClose, loadInsight } = useActions(logic)

    return (
        <LemonDrawer
            title="Edit metrics panel"
            onClose={requestClose}
            width="min(100vw, 800px)"
            resizable
            resizerLogicKey="dashboard-metrics-panel-editor"
            overlayTransparent
            footer={
                <div className="flex justify-end gap-2">
                    <LemonButton onClick={requestClose} disabledReason={saving ? 'Saving…' : undefined}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={save}
                        loading={saving}
                        disabledReason={saveDisabledReason}
                        data-attr="dashboard-metrics-panel-save"
                    >
                        {dashboardCount > 1 ? `Save on ${dashboardCount} dashboards` : 'Save panel'}
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4" data-attr="dashboard-metrics-panel-editor">
                {original && (
                    <LemonButton
                        to={urls.insightEdit(original.short_id as InsightShortId, props.dashboardId)}
                        target="_blank"
                        data-attr="dashboard-metrics-panel-full-editor"
                    >
                        Open full editor
                    </LemonButton>
                )}
                {error && (
                    <LemonBanner
                        type="error"
                        action={!original ? { children: 'Try again', onClick: () => loadInsight() } : undefined}
                    >
                        {error}
                    </LemonBanner>
                )}
                {originalLoading ? (
                    <Spinner />
                ) : (
                    query && (
                        <>
                            {dashboardCount > 1 && (
                                <LemonBanner type="warning">
                                    This insight appears on {dashboardCount} dashboards. Saving updates it everywhere.
                                    Duplicate the panel first to edit a separate copy.
                                </LemonBanner>
                            )}
                            {!!props.filtersOverride && (
                                <LemonBanner type="info">
                                    The preview uses this panel's dashboard filters. Saving keeps the insight's own time
                                    range and variable settings.
                                </LemonBanner>
                            )}
                            <fieldset disabled={saving} className="border-0 p-0 m-0 min-w-0 flex flex-col gap-3">
                                <LemonInput
                                    value={name}
                                    onChange={setName}
                                    aria-label="Panel name"
                                    placeholder="Panel name"
                                />
                                <MetricsQueryNode
                                    query={query}
                                    setQuery={setQuery}
                                    editMode
                                    filtersOverride={props.filtersOverride}
                                    context={{}}
                                />
                            </fieldset>
                        </>
                    )
                )}
            </div>
        </LemonDrawer>
    )
}
