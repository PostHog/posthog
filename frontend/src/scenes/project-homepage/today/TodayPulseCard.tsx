import './Today.scss'

import { IconArrowRight, IconHide, IconSparkles } from '@posthog/icons'
import { Button, Heading, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'

import type { HighlightMetricApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { todayNumber } from './todayNumbers'
import { TodayPulseExperimentResult } from './TodayPulseExperimentResult'
import { pulseChange, pulsePeriodCaption, pulsePriorLabel } from './todayPulseFacts'
import { TodayPulseMovers } from './TodayPulseMovers'
import { pulseOpenHandlers } from './todayPulseOpenHandlers'
import { TodayPulsePinButton } from './TodayPulsePinButton'
import type { TodayTone } from './todayTone'

function cardCaption(metric: HighlightMetricApi): string {
    return metric.experiment ? 'Experiment' : pulsePeriodCaption(metric)
}

const SUGGESTIONS: Partial<Record<string, string>> = {
    experiment: 'You run this experiment',
    evaluation: 'You created this evaluation',
}

const OPEN_LABELS: Partial<Record<string, string>> = {
    experiment: 'Open experiment',
    evaluation: 'Open evaluation',
}

function suggestionText(metric: HighlightMetricApi): string {
    return SUGGESTIONS[metric.reason ?? ''] ?? 'Suggested based on your usage'
}

function openLabel(metric: HighlightMetricApi): string {
    const label = OPEN_LABELS[metric.reason ?? '']
    if (label) {
        return label
    }
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
    hideDisabledReason,
    onHide,
}: {
    metric: HighlightMetricApi
    tone: TodayTone
    formatValue: (value: number) => string
    onOpen: () => void
    pinned: boolean
    pinDisabledReason?: string
    onTogglePin: () => void
    hideDisabledReason: string | null
    onHide: () => void
}): JSX.Element {
    const change = pulseChange(metric)
    const experiment = metric.experiment
    return (
        <div className="TodayPulseCard flex flex-col" data-attr="today-pulse-card">
            <div className="flex flex-col gap-4 p-3 pb-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-baseline justify-between gap-3">
                        <Text size="sm" weight="semibold" render={<span />} className="line-clamp-2">
                            {metric.name}
                        </Text>
                        <Text size="xs" variant="muted" render={<span />} className="shrink-0">
                            {cardCaption(metric)}
                        </Text>
                    </div>
                    {experiment ? (
                        <TodayPulseExperimentResult lift={metric.value} experiment={experiment} tone={tone} />
                    ) : (
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
                    )}
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
                {!pinned && (
                    <Text size="xs" variant="muted" render={<span />} className="inline-flex items-center gap-1">
                        <IconSparkles className="size-3 shrink-0" />
                        {suggestionText(metric)}
                    </Text>
                )}
            </div>
            <div
                className={cn(
                    'flex min-h-6 items-center justify-between gap-2 px-3 py-1',
                    metric.url ? 'border-t border-border' : '-mt-2'
                )}
            >
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
                    <TodayPulsePinButton pinned={pinned} disabledReason={pinDisabledReason} onToggle={onTogglePin} />
                    {!pinned && (
                        <Button
                            size="icon-xs"
                            aria-label="Ignore"
                            tooltip="Ignore"
                            disabledReason={hideDisabledReason}
                            onClick={onHide}
                            className="text-muted-foreground"
                            data-attr="today-pulse-card-hide"
                        >
                            <IconHide />
                        </Button>
                    )}
                </div>
            </div>
        </div>
    )
}
