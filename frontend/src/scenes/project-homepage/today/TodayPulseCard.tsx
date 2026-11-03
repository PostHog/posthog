import { useState } from 'react'

import { IconArrowRight, IconHide, IconInfo } from '@posthog/icons'
import {
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Heading,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayHoverCardFact } from '~/layout/today/TodayHoverCardFact'

import type { HighlightMetricApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { TodayPulseMovers } from './TodayPulseMovers'
import { pulsePeak, pulsePeriodCaption, pulseWhy } from './todayPulseFacts'
import { pulseOpenHandlers } from './todayPulseOpenHandlers'
import type { TodayTone } from './todayTone'

const PERIOD_FORMATS: Record<HighlightMetricApi['interval'], string> = {
    day: 'ddd, D MMM',
    week: '[week of] D MMM',
    month: 'MMMM YYYY',
}

function openLabel(metric: HighlightMetricApi): string {
    if (metric.dashboard_id !== null || metric.reason === 'dashboard') {
        return metric.dashboard_name ? `Open ${metric.dashboard_name}` : 'Open dashboard'
    }
    return metric.key.startsWith('insight:') ? 'Open insight' : 'Open as a trend'
}

export function TodayPulseCard({
    metric,
    tone,
    formatValue,
    onOpen,
    onHide,
}: {
    metric: HighlightMetricApi
    tone: TodayTone
    formatValue: (value: number) => string
    onOpen: () => void
    onHide: () => void
}): JSX.Element {
    const [whyOpen, setWhyOpen] = useState(false)
    const previous = metric.previous_value
    const peak = pulsePeak(metric)
    const why = pulseWhy(metric)
    return (
        <div className="flex flex-col" data-attr="today-pulse-card">
            <div className="flex flex-col gap-4 p-3 pb-3">
                <div className="flex flex-col">
                    <Text size="sm" weight="semibold" render={<span />} className="truncate">
                        {metric.name}
                    </Text>
                    <div className="mt-1 flex items-baseline gap-2">
                        <Heading size="xl" render={<span />} className="tabular-nums" translate="no">
                            {formatValue(metric.value)}
                        </Heading>
                        <span className="text-sm text-muted-foreground">
                            <TodayChange change={metric.change_pct} tone={tone} />
                        </span>
                    </div>
                    <Text size="xs" variant="muted" render={<span />} className="mt-1.5 opacity-75">
                        {pulsePeriodCaption(metric)}
                    </Text>
                </div>
                {(previous !== null || peak !== null) && (
                    <div className="flex flex-col gap-1">
                        {previous !== null && (
                            <TodayHoverCardFact label="Before">
                                <span className="tabular-nums">{formatValue(previous)}</span>
                            </TodayHoverCardFact>
                        )}
                        {peak !== null && (
                            <TodayHoverCardFact label={peak.label}>
                                <span className="tabular-nums">
                                    {formatValue(peak.value)}
                                    <span className="text-muted-foreground">
                                        {' '}
                                        · {peak.latest ?? dayjs(peak.start).format(PERIOD_FORMATS[metric.interval])}
                                    </span>
                                </span>
                            </TodayHoverCardFact>
                        )}
                    </div>
                )}
                {metric.movers.length > 1 && (
                    <div className="flex flex-col gap-1">
                        <Text size="xs" variant="muted" render={<span />} className="opacity-75">
                            What changed most
                        </Text>
                        <TodayPulseMovers movers={metric.movers} />
                    </div>
                )}
            </div>
            <Collapsible
                variant="folder"
                open={whyOpen}
                onOpenChange={setWhyOpen}
                className="flex flex-col border-t border-border px-3 py-1"
            >
                <div className="flex min-h-6 items-center justify-between gap-2">
                    {metric.url ? (
                        <Button
                            size="xs"
                            variant="link-muted"
                            className="-ms-2"
                            render={<LinkPrimitive to={metric.url} />}
                            {...pulseOpenHandlers(onOpen)}
                            data-attr="today-pulse-card-open"
                        >
                            {openLabel(metric)}
                            <IconArrowRight />
                        </Button>
                    ) : (
                        <span />
                    )}
                    <div className="-me-1.5 flex items-center">
                        <Button
                            size="icon-xs"
                            aria-label="Hide from Today"
                            tooltip="Hide from Today"
                            onClick={onHide}
                            className="text-muted-foreground"
                            data-attr="today-pulse-card-hide"
                        >
                            <IconHide />
                        </Button>
                        {why && (
                            <Tooltip>
                                <TooltipTrigger
                                    render={
                                        <CollapsibleTrigger
                                            iconOnly
                                            icon={<IconInfo />}
                                            className="text-muted-foreground"
                                            data-attr="today-pulse-card-why"
                                        />
                                    }
                                >
                                    Why you see this
                                </TooltipTrigger>
                                <TooltipContent>Why you see this</TooltipContent>
                            </Tooltip>
                        )}
                    </div>
                </div>
                {why && (
                    <CollapsibleContent className="px-0 pb-0">
                        <Text size="xs" variant="muted" className="m-0 pt-1">
                            {why}
                        </Text>
                    </CollapsibleContent>
                )}
            </Collapsible>
        </div>
    )
}
