import { LemonLabel, LemonSelect, SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Sparkline } from 'lib/components/Sparkline'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DataTableNode } from '~/queries/schema'
import { InsightType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
const EVENT_THRESHOLD_ALERT_LEVEL = 8000

export function HogFunctionEventEstimates(): JSX.Element | null {
    const { sparkline, sparklineLoading, eventsDataTableNode, showEventsList } =
        useValues(hogFunctionConfigurationLogic)

    const { setShowEventsList } = useActions(hogFunctionConfigurationLogic)

    if (!eventsDataTableNode) {
        return null
    }

    const dataTableNode: DataTableNode = {
        ...eventsDataTableNode,
        full: true,
    }

    const insightUrl = urls.insightNew(InsightType.SQL, null, dataTableNode)

    const canvasContent = {
        type: 'doc',
        content: [
            {
                type: 'ph-query',
                attrs: {
                    query: dataTableNode,
                },
            },
        ],
    }

    const canvasUrl = urls.canvas() + '#🦔=' + btoa(JSON.stringify(canvasContent))

    return (
        <div className="relative p-3 space-y-2 border rounded bg-bg-light">
            <LemonLabel>Matching events</LemonLabel>
            {sparkline && !sparklineLoading ? (
                <>
                    {sparkline.count > EVENT_THRESHOLD_ALERT_LEVEL ? (
                        <LemonBanner type="warning">
                            <b>Warning:</b> This destination would have triggered{' '}
                            <strong>
                                {sparkline.count ?? 0} time{sparkline.count !== 1 ? 's' : ''}
                            </strong>{' '}
                            in the last 7 days. Consider the impact of this function on your destination.
                        </LemonBanner>
                    ) : (
                        <p>
                            This destination would have triggered{' '}
                            <strong>
                                {sparkline.count ?? 0} time{sparkline.count !== 1 ? 's' : ''}
                            </strong>{' '}
                            in the last 7 days.
                        </p>
                    )}
                    <Sparkline type="bar" className="w-full h-20" data={sparkline.data} labels={sparkline.labels} />
                </>
            ) : sparklineLoading ? (
                <div className="min-h-20">
                    <SpinnerOverlay />
                </div>
            ) : (
                <p>The expected volume could not be calculated</p>
            )}

            <div className="flex flex-col gap-2 pt-2 border-t border-dashed">
                <LemonButton onClick={() => setShowEventsList(!showEventsList)} fullWidth center>
                    {showEventsList ? 'Hide matching events' : 'Show matching events'}
                </LemonButton>

                {showEventsList ? (
                    <>
                        <div className="flex items-start justify-end">
                            <LemonSelect
                                placeholder="Open in..."
                                onChange={(target) => {
                                    if (target === 'insight') {
                                        // Open a new tab
                                        window.open(insightUrl, '_blank')
                                    } else if (target === 'canvas') {
                                        // Open a new tab
                                        window.open(canvasUrl, '_blank')
                                    }
                                }}
                                options={[
                                    { label: 'New insight', value: 'insight' },
                                    { label: 'New canvas', value: 'canvas' },
                                ]}
                            />
                        </div>
                        <div className="flex flex-col flex-1 overflow-y-auto border rounded max-h-200">
                            {eventsDataTableNode && (
                                <Query
                                    query={{
                                        ...eventsDataTableNode,
                                        full: false,
                                        showEventFilter: false,
                                        showPropertyFilter: false,
                                        embedded: true,
                                        showOpenEditorButton: false,
                                        showHogQLEditor: false,
                                        showTimings: false,
                                    }}
                                />
                            )}
                        </div>
                    </>
                ) : null}
            </div>
        </div>
    )
}
