import './ImagePreview.scss'

import { LemonButton, LemonDivider, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TitledSnack } from 'lib/components/TitledSnack'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { POSTHOG_EVENT_PROMOTED_PROPERTIES } from 'lib/taxonomy'
import { autoCaptureEventToDescription, capitalizeFirstLetter, isString } from 'lib/utils'
import { insightUrlForEvent } from 'scenes/insights/utils'
import { eventPropertyFilteringLogic } from 'scenes/session-recordings/player/inspector/components/eventPropertyFilteringLogic'
import { DEFAULT_INSPECTOR_ROW_HEIGHT } from 'scenes/session-recordings/player/inspector/PlayerInspectorList'

import { ElementType } from '~/types'

import { InspectorListItemEvent } from '../playerInspectorLogic'
import { SimpleKeyValueList } from './SimpleKeyValueList'
export interface ItemEventProps {
    item: InspectorListItemEvent
}

function WebVitalEventSummary({ event }: { event: Record<string, any> }): JSX.Element {
    return (
        <>
            {event ? (
                <TitledSnack
                    type={event.rating === 'good' ? 'success' : 'default'}
                    title={event.name}
                    titleSuffix=""
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

function SummarizeWebVitals({ properties }: { properties: Record<string, any> }): JSX.Element {
    const { $web_vitals_FCP_event, $web_vitals_CLS_event, $web_vitals_INP_event, $web_vitals_LCP_event } = properties

    return (
        <div className="flex gap-1 items-center">
            <WebVitalEventSummary event={$web_vitals_FCP_event} />
            <WebVitalEventSummary event={$web_vitals_CLS_event} />
            <WebVitalEventSummary event={$web_vitals_INP_event} />
            <WebVitalEventSummary event={$web_vitals_LCP_event} />
        </div>
    )
}

function autocaptureToImage(
    elements: ElementType[]
): null | { src: string | undefined; width: string | undefined; height: string | undefined } {
    const find = elements.find((el) => el.tag_name === 'img')
    const image = {
        src: find?.attributes?.attr__src,
        width: find?.attributes?.attr__width,
        height: find?.attributes?.attr__height,
    }
    return image.src ? image : null
}

function AutocaptureImage({ item }: ItemEventProps): JSX.Element | null {
    const img = autocaptureToImage(item.data.elements)
    if (img) {
        return (
            <Tooltip
                title={
                    <div className="flex bg-bg-3000 items-center justify-center relative border-2">
                        {/* Transparent grid background */}
                        <div className="ImagePreview__background absolute h-full w-full" />

                        {/* Image preview */}
                        <img
                            className="relative z-10 max-h-100 object-contain"
                            src={img.src}
                            alt="Autocapture image src"
                            height={img.height || 'auto'}
                            width={img.width || 'auto'}
                        />
                    </div>
                }
            >
                <img
                    className="max-h-10"
                    src={img.src}
                    alt="Autocapture image src"
                    height={DEFAULT_INSPECTOR_ROW_HEIGHT}
                    width="auto"
                />
            </Tooltip>
        )
    }

    return null
}

export function ItemEvent({ item }: ItemEventProps): JSX.Element {
    const subValue =
        item.data.event === '$pageview' ? (
            item.data.properties.$pathname || item.data.properties.$current_url
        ) : item.data.event === '$screen' ? (
            item.data.properties.$screen_name
        ) : item.data.event === '$web_vitals' ? (
            <SummarizeWebVitals properties={item.data.properties} />
        ) : item.data.elements.length ? (
            <AutocaptureImage item={item} />
        ) : null

    return (
        <div data-attr="item-event" className="font-light w-full">
            <div className="flex flex-row w-full justify-between gap-2 items-center px-2 py-1 text-xs cursor-pointer">
                <div className="truncate">
                    <PropertyKeyInfo
                        className="font-medium"
                        disablePopover={true}
                        disableIcon={true}
                        ellipsis={true}
                        value={capitalizeFirstLetter(autoCaptureEventToDescription(item.data))}
                        type={TaxonomicFilterGroupType.Events}
                    />
                    {item.data.event === '$autocapture' ? <span className="text-muted-alt">(Autocapture)</span> : null}
                </div>
                {subValue ? (
                    <div className="text-muted-alt truncate" title={isString(subValue) ? subValue : undefined}>
                        {subValue}
                    </div>
                ) : null}
            </div>
        </div>
    )
}

export function ItemEventDetail({ item }: ItemEventProps): JSX.Element {
    const insightUrl = insightUrlForEvent(item.data)
    const { filterProperties } = useValues(eventPropertyFilteringLogic)

    const promotedKeys = POSTHOG_EVENT_PROMOTED_PROPERTIES[item.data.event]

    return (
        <div data-attr="item-event" className="font-light w-full">
            <div className="px-2 py-1 text-xs border-t">
                {insightUrl ? (
                    <>
                        <div className="flex justify-end">
                            <LemonButton
                                size="xsmall"
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
                        <SimpleKeyValueList item={filterProperties(item.data.properties)} promotedKeys={promotedKeys} />
                    )
                ) : (
                    <div className="text-muted-alt flex gap-1 items-center">
                        <Spinner textColored />
                        Loading...
                    </div>
                )}
            </div>
        </div>
    )
}
