import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TitledSnack } from 'lib/components/TitledSnack'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { autoCaptureEventToDescription, capitalizeFirstLetter } from 'lib/utils'
import { insightUrlForEvent } from 'scenes/insights/utils'

import { InspectorListItemEvent } from '../playerInspectorLogic'
import { SimpleKeyValueList } from './SimpleKeyValueList'

export interface ItemEventProps {
    item: InspectorListItemEvent
    expanded: boolean
    setExpanded: (expanded: boolean) => void
}

function webVitalEventSummary(event: Record<string, any>): JSX.Element {
    return (
        <>
            {event ? (
                <TitledSnack
                    type={event.rating === 'good' ? 'success' : 'default'}
                    title={event.name}
                    value={
                        <>
                            {event.rating}: {event.value.toFixed(2)}
                        </>
                    }
                />
            ) : null}
        </>
    )
}

function summarizeWebVitals(properties: Record<string, any>): JSX.Element {
    const { $web_vitals_FCP_event, $web_vitals_CLS_event, $web_vitals_INP_event, $web_vitals_LCP_event } = properties

    return (
        <div className="flex gap-1 items-center">
            {webVitalEventSummary($web_vitals_FCP_event)}
            {webVitalEventSummary($web_vitals_CLS_event)}
            {webVitalEventSummary($web_vitals_INP_event)}
            {webVitalEventSummary($web_vitals_LCP_event)}
        </div>
    )
}

export function ItemEvent({ item, expanded, setExpanded }: ItemEventProps): JSX.Element {
    const insightUrl = insightUrlForEvent(item.data)

    const subValue =
        item.data.event === '$pageview'
            ? item.data.properties.$pathname || item.data.properties.$current_url
            : item.data.event === '$screen'
            ? item.data.properties.$screen_name
            : item.data.event === '$web_vitals'
            ? summarizeWebVitals(item.data.properties)
            : undefined

    let promotedKeys: string[] | undefined = undefined
    if (item.data.event === '$pageview') {
        promotedKeys = ['$current_url', '$title', '$referrer']
    } else if (item.data.event === '$screen') {
        promotedKeys = ['$screen_name']
    } else if (item.data.event === '$web_vitals') {
        promotedKeys = [
            '$web_vitals_FCP_value',
            '$web_vitals_CLS_value',
            '$web_vitals_INP_value',
            '$web_vitals_LCP_value',
            '$web_vitals_FCP_event',
            '$web_vitals_CLS_event',
            '$web_vitals_INP_event',
            '$web_vitals_LCP_event',
        ]
    }

    return (
        <div data-attr="item-event">
            <LemonButton noPadding onClick={() => setExpanded(!expanded)} fullWidth>
                <div className="flex gap-2 items-center p-2 text-xs cursor-pointer truncate">
                    <PropertyKeyInfo
                        className="font-medium shrink-0"
                        disablePopover
                        ellipsis={true}
                        value={capitalizeFirstLetter(autoCaptureEventToDescription(item.data))}
                        type={TaxonomicFilterGroupType.Events}
                    />
                    {item.data.event === '$autocapture' ? <span className="text-muted-alt">(Autocapture)</span> : null}
                    {subValue ? (
                        <span className="text-muted-alt truncate" title={subValue}>
                            {subValue}
                        </span>
                    ) : null}
                </div>
            </LemonButton>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    {insightUrl ? (
                        <>
                            <div className="flex justify-end">
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    sideIcon={<IconOpenInNew />}
                                    data-attr="recordings-event-to-insights"
                                    to={insightUrl}
                                    targetBlank
                                >
                                    Try out in Insights
                                </LemonButton>
                            </div>
                            <LemonDivider dashed />
                        </>
                    ) : null}

                    {item.data.fullyLoaded ? (
                        item.data.event === '$exception' ? (
                            <ErrorDisplay eventProperties={item.data.properties} />
                        ) : (
                            <SimpleKeyValueList item={item.data.properties} promotedKeys={promotedKeys} />
                        )
                    ) : (
                        <div className="text-muted-alt flex gap-1 items-center">
                            <Spinner textColored />
                            Loading...
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
