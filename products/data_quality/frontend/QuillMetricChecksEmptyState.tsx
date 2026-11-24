import { useState } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
    Label,
    RadioGroup,
    RadioGroupItem,
    Text,
    cn,
} from '@posthog/quill'

import { METRIC_STARTER_CHECKS, MetricStarterKey } from './metricStarterChecks'

const DEFAULT_STARTER: MetricStarterKey = 'has_rows'

export interface QuillMetricChecksEmptyStateProps {
    metricName?: string
    onStart: (starterKey: MetricStarterKey | null) => void
    disabledReason?: string
}

export function QuillMetricChecksEmptyState({
    metricName,
    onStart,
    disabledReason,
}: QuillMetricChecksEmptyStateProps): JSX.Element {
    const [selectedStarter, setSelectedStarter] = useState<MetricStarterKey>(DEFAULT_STARTER)

    return (
        <Empty data-attr="data-quality-metric-checks-empty">
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color="var(--color-product-data-warehouse-light)">
                        <IconCheckCircle />
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>
                    {metricName ? `No checks on ${metricName} yet` : 'No checks on this metric yet'}
                </EmptyTitle>
                <EmptyDescription>
                    A check runs on this metric every day and fails when the result looks wrong, for example when it
                    comes back empty or drops suddenly. Pick a starting point, then adjust it before you save.
                </EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="w-full">
                <RadioGroup
                    value={selectedStarter}
                    onValueChange={(starterKey) => setSelectedStarter(starterKey as MetricStarterKey)}
                    aria-label="Starting check"
                    className="flex w-full flex-col gap-2 text-left"
                >
                    {METRIC_STARTER_CHECKS.map((starter) => (
                        <Label
                            key={starter.key}
                            className={cn(
                                'flex w-full cursor-pointer items-start gap-3 rounded-md border p-3 text-pretty hover:bg-fill-hover',
                                selectedStarter === starter.key && 'bg-fill-selected hover:bg-fill-selected'
                            )}
                            data-attr={`data-quality-metric-starter-${starter.key}`}
                        >
                            <RadioGroupItem value={starter.key} className="mt-0.5" />
                            <span className="flex min-w-0 flex-col gap-0.5">
                                <span className="font-medium">{starter.title}</span>
                                <Text size="xs" variant="muted" render={<span />}>
                                    {starter.description}
                                </Text>
                            </span>
                        </Label>
                    ))}
                </RadioGroup>
                <div className="flex flex-wrap justify-center gap-2">
                    <Button
                        variant="primary"
                        onClick={() => onStart(selectedStarter)}
                        disabledReason={disabledReason}
                        data-attr="data-quality-metric-add-starter-check"
                    >
                        Add a check
                    </Button>
                    <Button
                        variant="outline"
                        onClick={() => onStart(null)}
                        disabledReason={disabledReason}
                        data-attr="data-quality-metric-write-own-sql"
                    >
                        Write your own SQL
                    </Button>
                </div>
            </EmptyContent>
        </Empty>
    )
}
