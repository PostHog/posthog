import './Today.scss'

import { useState } from 'react'

import { IconArrowRight, IconHide, IconInfo, IconPin, IconPinFilled } from '@posthog/icons'
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

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'

import type { HighlightMetricApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { todayNumber } from './todayNumbers'
import { pulseChange, pulsePeriodCaption, pulsePriorLabel, pulseWhy } from './todayPulseFacts'
import { TodayPulseMovers } from './TodayPulseMovers'
import { pulseOpenHandlers } from './todayPulseOpenHandlers'
import type { TodayTone } from './todayTone'

function openLabel(metric: HighlightMetricApi): string {
    return metric.dashboard_id !== null || metric.reason === 'dashboard' ? 'Open dashboard' : 'Open insight'
}

export function TodayPulseCard({
    metric,
    tone,
    formatValue,
    onOpen,
    pinned,
    pinDisabledReason,
    onTogglePin,
    onHide,
}: {
    metric: HighlightMetricApi
    tone: TodayTone
    formatValue: (value: number) => string
    onOpen: () => void
    pinned: boolean
    pinDisabledReason?: string
    onTogglePin: () => void
    onHide: () => void
}): JSX.Element {
    const [whyOpen, setWhyOpen] = useState(false)
    const why = pinned ? 'You keep this number on your home. Change it with Edit.' : pulseWhy(metric)
    const change = pulseChange(metric)
    return (
        <div className="TodayPulseCard flex flex-col" data-attr="today-pulse-card">
            <div className="flex flex-col gap-4 p-3 pb-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-baseline justify-between gap-3">
                        <Text size="sm" weight="semibold" render={<span />} className="line-clamp-2">
                            {metric.name}
                        </Text>
                        <Text size="xs" variant="muted" render={<span />} className="shrink-0">
                            {pulsePeriodCaption(metric)}
                        </Text>
                    </div>
                    <div className="flex flex-wrap items-baseline gap-x-2">
                        <Heading size="xl" render={<span />} className="tabular-nums" translate="no">
                            {formatValue(metric.value)}
                        </Heading>
                        {change.value !== null && (
                            <span className="text-sm text-muted-foreground">
                                <TodayChange change={change.value} unit={change.unit} tone={tone} />
                                <span> {pulsePriorLabel(metric)}</span>
                            </span>
                        )}
                    </div>
                </div>
                {metric.movers.length > 1 && (
                    <div className="flex flex-col gap-1">
                        <Text size="xs" variant="muted" render={<span />}>
                            What changed most
                        </Text>
                        <TodayPulseMovers
                            movers={metric.movers}
                            formatValue={metric.value_format ? formatValue : todayNumber}
                        />
                    </div>
                )}
            </div>
            <Collapsible
                variant="folder"
                open={whyOpen}
                onOpenChange={setWhyOpen}
                className={cn('flex flex-col px-3 py-1', metric.url ? 'border-t border-border' : '-mt-2')}
            >
                <div className="flex min-h-6 items-center justify-between gap-2">
                    {metric.url ? (
                        <LinkPrimitive
                            to={metric.url}
                            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                            {...pulseOpenHandlers(onOpen)}
                            data-attr="today-pulse-card-open"
                        >
                            {openLabel(metric)}
                            <IconArrowRight />
                        </LinkPrimitive>
                    ) : (
                        <span />
                    )}
                    <div className="-me-1.5 flex items-center">
                        <Button
                            size="icon-xs"
                            aria-label={pinned ? 'Unpin from your home' : 'Pin to your home'}
                            tooltip={pinned ? 'Unpin from your home' : 'Pin to your home'}
                            aria-pressed={pinned}
                            disabledReason={pinDisabledReason}
                            onClick={onTogglePin}
                            className={pinned ? undefined : 'text-muted-foreground'}
                            data-attr="today-pulse-card-pin"
                        >
                            {pinned ? <IconPinFilled /> : <IconPin />}
                        </Button>
                        {!pinned && (
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
                        )}
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
                    <CollapsibleContent className="px-0 pb-2">
                        <Text size="xs" variant="muted" className="m-0 pt-1">
                            {why}
                        </Text>
                    </CollapsibleContent>
                )}
            </Collapsible>
        </div>
    )
}
