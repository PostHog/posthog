import { useActions, useValues } from 'kea'

import { LemonLabel, LemonSelect, SpinnerOverlay } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { base64Encode } from 'lib/utils'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DataTableNode } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'

const EVENT_THRESHOLD_ALERT_LEVEL = 8000

export function HogFunctionEventEstimates(): JSX.Element | null {
    const { sparkline, sparklineLoading, eventsDataTableNode, showEventsList, type, configuration } =
        useValues(hogFunctionConfigurationLogic)

    const { setShowEventsList } = useActions(hogFunctionConfigurationLogic)

    const hasMasking = !!configuration.masking

    if (!eventsDataTableNode) {
        return null
    }

    const dataTableNode: DataTableNode = {
        ...eventsDataTableNode,
        full: true,
    }

    const insightUrl = urls.insightNew({ type: InsightType.SQL, query: dataTableNode })

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

    const canvasUrl = urls.canvas() + '#🦔=' + base64Encode(JSON.stringify(canvasContent))

    return (
        <div className="relative p-3 rounded border deprecated-space-y-2 bg-surface-primary">
            <LemonLabel>Matching events</LemonLabel>
            {sparkline && !sparklineLoading ? (
                <>
                    {sparkline.count > EVENT_THRESHOLD_ALERT_LEVEL && type !== 'transformation' ? (
                        <LemonBanner type="warning">
                            <b>Warning:</b> This destination would have triggered{' '}
                            <strong>
                                {sparkline.count ?? 0} time{sparkline.count !== 1 ? 's' : ''}
                            </strong>{' '}
                            in the last 7 days. Consider the impact of this function on your destination.
                        </LemonBanner>
                    ) : (
                        <p>
                            This {type} would have triggered{' '}
                            <strong>
                                {sparkline.count ?? 0} time{sparkline.count !== 1 ? 's' : ''}
                            </strong>{' '}
                            in the last 7 days.
                        </p>
                    )}

                    {hasMasking && <p>The estimate does not take into account trigger options.</p>}

                    {'warning' in sparkline && sparkline.warning && (
                        <LemonBanner type="info">{sparkline.warning}</LemonBanner>
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
                        <div className="flex justify-end items-start">
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
                        <div className="flex overflow-y-auto flex-col flex-1 rounded border max-h-200">
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
