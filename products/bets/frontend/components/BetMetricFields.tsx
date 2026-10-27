import { useActions, useValues } from 'kea'

import {
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import { betFormLogic } from '../logics/betFormLogic'
import { BetResourceLink } from './BetResourceLink'

export function BetMetricFields({ id }: { id: string }): JSX.Element {
    const { form, insights, insightsLoading } = useValues(betFormLogic({ id }))
    const { change, selectPrimaryInsight } = useActions(betFormLogic({ id }))
    const items = [
        { value: '', label: 'Choose a saved insight' },
        ...insights.map((insight) => ({
            value: insight.short_id,
            label: insight.name || insight.derived_name || insight.short_id,
        })),
    ]
    const secondary = [
        { value: '', label: 'Add a secondary metric' },
        ...items.filter(
            (item) =>
                item.value &&
                item.value !== form.goal_insight &&
                !form.secondary_metrics?.some((metric) => metric.insight === item.value)
        ),
    ]
    return (
        <>
            <Field>
                <FieldLabel htmlFor="bet-primary">Primary metric</FieldLabel>
                <Input
                    id="bet-primary"
                    required
                    value={form.goal_metric}
                    onChange={(event) => change({ goal_metric: event.target.value })}
                    placeholder="For example, weekly successful searches"
                />
                <FieldDescription>The one metric that defines success for this bet.</FieldDescription>
            </Field>
            <Field>
                <FieldLabel htmlFor="bet-insight">Measure with</FieldLabel>
                <Select
                    value={form.goal_insight || ''}
                    items={items}
                    onValueChange={(value) => selectPrimaryInsight(value ?? '')}
                    disabled={insightsLoading}
                >
                    <SelectTrigger id="bet-insight" aria-label="Primary metric insight" className="w-full">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {items.map((item) => (
                            <SelectItem key={item.value} value={item.value}>
                                {item.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <FieldDescription>Use a saved PostHog insight with one series.</FieldDescription>
            </Field>
            <div className="Bets__goalFields">
                <Field>
                    <FieldLabel htmlFor="bet-direction">Goal direction</FieldLabel>
                    <Select
                        value={form.direction}
                        items={[
                            { value: 'increase', label: 'At least this target' },
                            { value: 'decrease', label: 'At most this target' },
                        ]}
                        onValueChange={(value) => change({ direction: value === 'decrease' ? 'decrease' : 'increase' })}
                    >
                        <SelectTrigger id="bet-direction" aria-label="Goal direction" className="w-full h-8">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="increase">At least this target</SelectItem>
                            <SelectItem value="decrease">At most this target</SelectItem>
                        </SelectContent>
                    </Select>
                </Field>
                <Field>
                    <FieldLabel htmlFor="bet-target">Target</FieldLabel>
                    <Input
                        id="bet-target"
                        required
                        type="number"
                        step="any"
                        value={form.target}
                        onChange={(event) => change({ target: event.target.value })}
                        placeholder="85"
                    />
                </Field>
                <Field>
                    <FieldLabel htmlFor="bet-unit">Unit</FieldLabel>
                    <Input
                        id="bet-unit"
                        value={form.unit ?? ''}
                        onChange={(event) => change({ unit: event.target.value })}
                        placeholder="%, people, seconds…"
                    />
                </Field>
            </div>
            <Field>
                <FieldLabel htmlFor="bet-secondary">Secondary metrics</FieldLabel>
                <FieldDescription>Optional supporting metrics to watch for tradeoffs.</FieldDescription>
                {form.secondary_metrics?.map((metric) => (
                    <div key={metric.insight} className="flex min-w-0 flex-wrap items-center justify-between gap-3">
                        <BetResourceLink
                            kind="insight"
                            title={metric.name}
                            href={urls.insightView(metric.insight as InsightShortId)}
                            id={metric.insight}
                        />
                        <div className="flex flex-wrap items-center gap-2">
                            <Select
                                value={metric.direction ?? 'increase'}
                                items={[
                                    { value: 'increase', label: 'Higher is better' },
                                    { value: 'decrease', label: 'Lower is better' },
                                ]}
                                onValueChange={(direction) =>
                                    change({
                                        secondary_metrics: form.secondary_metrics?.map((entry) =>
                                            entry.insight === metric.insight
                                                ? {
                                                      ...entry,
                                                      direction: direction === 'decrease' ? 'decrease' : 'increase',
                                                  }
                                                : entry
                                        ),
                                    })
                                }
                            >
                                <SelectTrigger aria-label={`${metric.name}: desirable direction`}>
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="increase">Higher is better</SelectItem>
                                    <SelectItem value="decrease">Lower is better</SelectItem>
                                </SelectContent>
                            </Select>
                            <Input
                                className="w-20"
                                type="number"
                                min={0}
                                max={100}
                                step="any"
                                value={(metric.max_regression ?? 0.01) * 100}
                                aria-label={`${metric.name}: maximum regression percent`}
                                onChange={(event) =>
                                    change({
                                        secondary_metrics: form.secondary_metrics?.map((entry) =>
                                            entry.insight === metric.insight
                                                ? { ...entry, max_regression: Number(event.target.value) / 100 }
                                                : entry
                                        ),
                                    })
                                }
                            />
                            <span className="text-xs text-muted">% maximum regression</span>
                        </div>
                        <Button
                            size="sm"
                            variant="link-muted"
                            aria-label={`Remove ${metric.name}`}
                            onClick={() =>
                                change({
                                    secondary_metrics: form.secondary_metrics?.filter(
                                        (entry) => entry.insight !== metric.insight
                                    ),
                                })
                            }
                        >
                            Remove
                        </Button>
                    </div>
                ))}
                {(form.secondary_metrics?.length ?? 0) < 5 && (
                    <Select
                        value=""
                        items={secondary}
                        onValueChange={(value) => {
                            const item = secondary.find((entry) => entry.value === value)
                            if (item?.value) {
                                change({
                                    secondary_metrics: [
                                        ...(form.secondary_metrics ?? []),
                                        { insight: item.value, name: item.label },
                                    ],
                                })
                            }
                        }}
                    >
                        <SelectTrigger id="bet-secondary" aria-label="Add secondary metric">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {secondary.map((item) => (
                                <SelectItem key={item.value} value={item.value}>
                                    {item.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                )}
            </Field>
        </>
    )
}
