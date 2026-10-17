import { useActions, useValues } from 'kea'

import { LemonLabel, SpinnerOverlay } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DataTableNode } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'

const EVENT_THRESHOLD_ALERT_LEVEL = 8000

export function HogFunctionEventEstimates(): JSX.Element | null {
    const { sparkline, sparklineLoading, eventsDataTableNode, showEventsList, type, configuration, useMapping } =
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
    const matchCount = sparkline?.count ?? 0
    const matchCountDescription = useMapping ? (
        <>
            At least one mapping matched{' '}
            <strong>
                {matchCount} event{matchCount !== 1 ? 's' : ''}
            </strong>
        </>
    ) : (
        <>
            This {type} would have triggered{' '}
            <strong>
                {matchCount} time{matchCount !== 1 ? 's' : ''}
            </strong>
        </>
    )

    return (
        <div className="relative p-3 rounded border deprecated-space-y-2 bg-surface-primary">
            <LemonLabel>{useMapping ? 'Matching events across all mappings' : 'Matching events'}</LemonLabel>
            {useMapping ? (
                <p className="text-sm text-secondary">
                    This preview counts each matching event once, even if it matches several mappings. Matchers only
                    filter their own mapping, and one event may trigger multiple destination invocations.
                </p>
            ) : null}
            {sparkline && !sparklineLoading ? (
                <>
                    {sparkline.count > EVENT_THRESHOLD_ALERT_LEVEL && type !== 'transformation' ? (
                        <LemonBanner type="warning">
                            <b>Warning:</b> {matchCountDescription} in the last 7 days. Consider the impact of this
                            function on your destination.
                        </LemonBanner>
                    ) : (
                        <p>{matchCountDescription} in the last 7 days.</p>
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
                            <LemonButton type="secondary" size="small" to={insightUrl} targetBlank>
                                New insight
                            </LemonButton>
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
