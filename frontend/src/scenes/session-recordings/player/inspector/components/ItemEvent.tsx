import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
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

export function ItemEvent({ item, expanded, setExpanded }: ItemEventProps): JSX.Element {
    const insightUrl = insightUrlForEvent(item.data)

    const subValue =
        item.data.event === '$pageview'
            ? item.data.properties.$pathname || item.data.properties.$current_url
            : item.data.event === '$screen'
            ? item.data.properties.$screen_name
            : undefined

    return (
        <div data-attr="item-event">
            <LemonButton noPadding onClick={() => setExpanded(!expanded)} fullWidth>
                <div className="flex gap-2 items-start p-2 text-xs cursor-pointer truncate">
                    <PropertyKeyInfo
                        className="font-medium shrink-0"
                        disablePopover
                        ellipsis={true}
                        value={capitalizeFirstLetter(autoCaptureEventToDescription(item.data))}
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
                            <ErrorDisplay event={item.data} />
                        ) : (
                            <SimpleKeyValueList item={item.data.properties} />
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
