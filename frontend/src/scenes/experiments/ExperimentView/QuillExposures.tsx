import type { ColumnDef } from '@tanstack/react-table'
import { type ReactNode } from 'react'

import { IconCheckCircle, IconCorrelationAnalysis, IconInfo, IconPencil, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    DataTable,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { EXPERIMENT_VARIANT_MULTIPLE } from 'products/experiments/frontend/constants'

import {
    EXPOSURES_HELP,
    ExposuresChart,
    type ExposuresCardModel,
    HOLDOUT_HELP,
    NO_EXPOSURES_DESCRIPTION,
    NO_EXPOSURES_TITLE,
    WINNER_HELP,
} from './exposuresCard'
import { QuillHelpTooltip, QuillSectionHeading } from './QuillCardParts'
import { VariantTag } from './VariantTag'

const SAMPLE_RATIO_TONE = {
    warning: { className: 'text-warning-foreground font-semibold', icon: <IconWarning /> },
    info: { className: 'text-muted-foreground', icon: <IconInfo /> },
    success: { className: 'text-success-foreground', icon: <IconCheckCircle /> },
}

function BadgeWithTooltip({
    variant,
    tooltip,
    children,
}: {
    variant: 'default' | 'info' | 'success'
    tooltip: string
    children: ReactNode
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<Badge variant={variant} tabIndex={0} />}>{children}</TooltipTrigger>
            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
        </Tooltip>
    )
}

type ExposureRow = { variant: string; kind: 'variant' | 'excluded' | 'holdout' | 'total' }

function exposureColumns(card: ExposuresCardModel): ColumnDef<ExposureRow>[] {
    const { exposures, totalExposures, isEnded } = card
    return [
        {
            id: 'variant',
            header: 'Variant',
            meta: { expand: true },
            cell: ({ row: { original } }) =>
                original.kind === 'total' ? (
                    'Total'
                ) : (
                    <div className="flex items-center gap-1.5">
                        <VariantTag variantKey={original.variant} />
                        {original.variant === card.winnerKey && (
                            <BadgeWithTooltip variant="success" tooltip={WINNER_HELP}>
                                Winner
                            </BadgeWithTooltip>
                        )}
                        {card.winningKeys.has(original.variant) && (
                            <BadgeWithTooltip variant="info" tooltip={card.winningTooltip}>
                                Winning
                            </BadgeWithTooltip>
                        )}
                        {original.variant === EXPERIMENT_VARIANT_MULTIPLE && (
                            <>
                                <Text size="xs" variant="muted" render={<span />}>
                                    ({card.multipleTreatmentLabel})
                                </Text>
                                {!isEnded && (
                                    <Button
                                        size="icon-xs"
                                        aria-label="Edit exposure criteria"
                                        tooltip="Edit exposure criteria"
                                        onClick={card.openExposureCriteria}
                                    >
                                        <IconPencil />
                                    </Button>
                                )}
                            </>
                        )}
                    </div>
                ),
        },
        {
            id: 'exposures',
            header: 'Exposures',
            cell: ({ row: { original } }) =>
                original.kind === 'total' ? (
                    humanFriendlyNumber(totalExposures)
                ) : original.kind === 'variant' ? (
                    humanFriendlyNumber(exposures?.total_exposures[original.variant] ?? 0)
                ) : (
                    <span className="text-muted-foreground">—</span>
                ),
        },
        {
            id: 'percentage',
            header: '%',
            cell: ({ row: { original } }) =>
                original.kind === 'total' ? (
                    totalExposures > 0 ? (
                        '100.0%'
                    ) : (
                        '-%'
                    )
                ) : original.kind === 'excluded' ? (
                    <span className="text-muted-foreground">Excluded from analysis</span>
                ) : original.kind === 'holdout' ? (
                    <span className="text-muted-foreground">Reserved (holdout)</span>
                ) : (
                    (card.variantPercentage(original.variant) ?? '-%')
                ),
        },
    ]
}

export function QuillExposures(card: ExposuresCardModel): JSX.Element {
    const { exposures, totalExposures, isEnded, srmLine } = card
    const timeseries = exposures?.timeseries ?? []
    const hasTable = timeseries.length > 0
    const rows: ExposureRow[] = [
        ...timeseries.map(({ variant }) => ({ variant, kind: 'variant' as const })),
        ...card.excludedVariants.map((variant) => ({ variant, kind: 'excluded' as const })),
        ...(card.holdoutVariantKey ? [{ variant: card.holdoutVariantKey, kind: 'holdout' as const }] : []),
        { variant: 'total', kind: 'total' },
    ]

    return (
        <Card flush className="h-full">
            <CardContent className="flex h-full flex-col gap-4">
                <div className={cn('flex flex-col gap-4 px-4', !hasTable && 'pb-4')}>
                    <div className="flex items-center gap-1">
                        <QuillSectionHeading>Exposures</QuillSectionHeading>
                        <QuillHelpTooltip label="Exposures" help={EXPOSURES_HELP} />
                        {card.holdoutName && (
                            <BadgeWithTooltip variant="default" tooltip={HOLDOUT_HELP}>
                                {card.holdoutName}
                            </BadgeWithTooltip>
                        )}
                        {isEnded ? (
                            <Text size="xs" variant="muted" render={<span className="ml-auto" />}>
                                Exposure criteria: <span className="text-foreground">{card.exposureCriteriaLabel}</span>
                            </Text>
                        ) : (
                            <Button
                                className="ml-auto"
                                tooltip={card.exposureCriteriaLabel}
                                onClick={card.openExposureCriteria}
                            >
                                Exposure criteria
                            </Button>
                        )}
                    </div>
                    {card.exposuresLoading ? (
                        <div className="relative flex h-50 flex-col">
                            <Skeleton className="h-full w-full" />
                            {card.exposuresLoadingSlowly && (
                                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
                                    <Text size="xs" variant="muted">
                                        Still loading exposures after {card.exposuresElapsedSeconds}s
                                    </Text>
                                    <Button variant="outline" onClick={card.retry}>
                                        Retry
                                    </Button>
                                </div>
                            )}
                        </div>
                    ) : totalExposures === 0 ? (
                        <Empty className="h-50">
                            <EmptyHeader>
                                <IconStack>
                                    <IconStackItem color="var(--color-product-experiments-light)">
                                        <IconCorrelationAnalysis />
                                    </IconStackItem>
                                </IconStack>
                                <EmptyTitle>{NO_EXPOSURES_TITLE}</EmptyTitle>
                                <EmptyDescription>{NO_EXPOSURES_DESCRIPTION}</EmptyDescription>
                            </EmptyHeader>
                            {!isEnded && (
                                <EmptyContent>
                                    <Button variant="outline" onClick={card.editExposureCriteriaFromEmpty}>
                                        <IconPencil />
                                        Edit exposure criteria
                                    </Button>
                                </EmptyContent>
                            )}
                        </Empty>
                    ) : (
                        exposures && <ExposuresChart exposures={exposures} className="relative flex h-50 flex-col" />
                    )}
                </div>

                {hasTable && (
                    <div className="mt-auto flex flex-col">
                        <DataTable
                            columns={exposureColumns(card)}
                            data={rows}
                            fullWidth
                            getRowId={(row) => row.variant}
                            rowClassName={(row) =>
                                row.kind === 'total'
                                    ? 'font-semibold'
                                    : row.kind === 'variant'
                                      ? undefined
                                      : 'opacity-60'
                            }
                        />
                        {srmLine && card.hasSampleRatioTest && exposures?.sample_ratio_mismatch && (
                            <div className="flex items-center gap-1 border-t border-border px-4 py-3">
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <span
                                                tabIndex={0}
                                                className={cn(
                                                    'flex items-center gap-1 text-xs',
                                                    SAMPLE_RATIO_TONE[srmLine.tone].className
                                                )}
                                            />
                                        }
                                    >
                                        {SAMPLE_RATIO_TONE[srmLine.tone].icon}
                                        {srmLine.label}
                                    </TooltipTrigger>
                                    <TooltipContent className="max-w-80">{srmLine.tooltip}</TooltipContent>
                                </Tooltip>
                                <Text size="xs" variant="muted" render={<span />}>
                                    (p ={' '}
                                    {srmLine.tone === 'success'
                                        ? exposures.sample_ratio_mismatch.p_value.toFixed(3)
                                        : exposures.sample_ratio_mismatch.p_value.toExponential(2)}
                                    )
                                </Text>
                            </div>
                        )}
                    </div>
                )}
            </CardContent>
        </Card>
    )
}
