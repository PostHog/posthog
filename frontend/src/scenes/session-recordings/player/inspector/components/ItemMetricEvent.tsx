import { Link } from 'lib/lemon-ui/Link'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { InspectorListItemMetricEvent } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

export interface ItemMetricEventProps {
    item: InspectorListItemMetricEvent
}

export function ItemMetricEvent({ item }: ItemMetricEventProps): JSX.Element {
    return (
        <div data-attr="item-metric-event" className="font-light w-full">
            <div className="flex flex-row w-full gap-2 items-center px-2 py-1 text-xs">
                <div className="truncate flex-1 min-w-0 font-medium">Fired a {item.data.metricName} event</div>
                <div className="flex items-center gap-1 shrink-0 text-secondary">
                    <span className="truncate max-w-[40ch]" title={item.data.experimentName}>
                        {item.data.experimentName}
                    </span>
                </div>
            </div>
        </div>
    )
}

export function ItemMetricEventDetail({ item }: ItemMetricEventProps): JSX.Element {
    const { experimentId, experimentName, metricName, eventCount } = item.data

    return (
        <div data-attr="item-metric-event" className="font-light w-full">
            <div className="px-2 py-1 text-xs border-t flex flex-col gap-1">
                <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="text-secondary shrink-0">Experiment</span>
                    <Link
                        to={urls.experiment(experimentId)}
                        target="_blank"
                        className="truncate"
                        onClick={() => {
                            void addProductIntentForCrossSell({
                                from: ProductKey.SESSION_REPLAY,
                                to: ProductKey.EXPERIMENTS,
                                intent_context: ProductIntentContext.SESSION_REPLAY_EXPERIMENT_LINK_CLICKED,
                                metadata: { experiment_id: experimentId },
                            })
                        }}
                    >
                        {experimentName}
                    </Link>
                </div>
                <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="text-secondary shrink-0">Metric</span>
                    <span className="truncate">{metricName}</span>
                </div>
                <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="text-secondary shrink-0">Events in this session</span>
                    <span className="truncate">{eventCount}</span>
                </div>
                <div className="text-secondary">
                    Counts every matching event in this session, which can differ from what the experiment analysis
                    counts.
                </div>
            </div>
        </div>
    )
}
