import { useValues } from 'kea'
import { type MouseEvent, useEffect, useMemo, useRef, useState } from 'react'

import { Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { BucketStatusEnumApi, EvaluationResultApi } from '../../generated/api.schemas'
import { compactHeadline, describeBucket, formatBucket } from './evaluationOverviewDisplay'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/** Below this many graded results the backend never marks a bucket unusual, so the cell is greyed as unreliable. */
const LOW_EVIDENCE_BUCKET_VOLUME = 30

const STATUS_CLASSES: Record<BucketStatusEnumApi, string> = {
    dip: 'bg-warning border-transparent',
    normal: 'bg-muted opacity-40 border-transparent',
    none: 'border-dashed border-primary',
}

const STATUS_LABELS: Record<BucketStatusEnumApi, string> = {
    dip: 'Unusual for this evaluation',
    normal: 'In line with its usual results',
    none: 'No graded results',
}

const LOW_EVIDENCE_CLASSES = 'bg-muted opacity-15 border-transparent'

const LEGEND_ORDER: BucketStatusEnumApi[] = ['dip', 'normal', 'none']

interface HoveredCell {
    row: number
    index: number
    /** The cell's box relative to the grid, where the shared tooltip anchors. */
    box: { left: number; top: number; width: number; height: number }
}

function isLowEvidence(row: EvaluationResultApi, index: number): boolean {
    return row.bucketStatus[index] === 'normal' && (row.trend.volume[index] ?? 0) < LOW_EVIDENCE_BUCKET_VOLUME
}

export function EvaluationStatusGrid(): JSX.Element {
    const { statusGridRows, buckets, interval, evaluationUrl } = useValues(evaluationsOverviewLogic)
    // One tooltip follows the pointer, because a tooltip per cell makes a large grid slow to render.
    const [hovered, setHovered] = useState<HoveredCell | null>(null)
    const gridRef = useRef<HTMLDivElement>(null)
    const labels = useMemo(() => buckets.map((bucket) => formatBucket(bucket, interval)), [buckets, interval])

    // A tooltip held open with `visible` loses its own Escape and scroll dismissal, so the grid restores both. Both
    // listen in the capture phase, because Base UI stops Escape before it bubbles to the window.
    useEffect(() => {
        if (!hovered) {
            return
        }
        const dismiss = (): void => setHovered(null)
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                dismiss()
            }
        }
        window.addEventListener('keydown', onKeyDown, true)
        window.addEventListener('scroll', dismiss, true)
        return () => {
            window.removeEventListener('keydown', onKeyDown, true)
            window.removeEventListener('scroll', dismiss, true)
        }
    }, [hovered])

    // Memoized so that moving the pointer renders only the tooltip, not every cell.
    const rows = useMemo(
        () =>
            statusGridRows.map((row, rowIndex) => (
                <div key={row.id} className={cn('flex items-center gap-3', row.lowEvidence && 'opacity-60')}>
                    <Link
                        to={evaluationUrl(row.id)}
                        subtle
                        className="w-28 @2xl:w-48 shrink-0 truncate text-primary"
                        data-attr="evaluation-overview-status-grid-name"
                    >
                        {row.name}
                    </Link>
                    <span className="flex-1 min-w-0 flex gap-0.5">
                        {row.bucketStatus.map((status, index) => (
                            <span
                                key={buckets[index] ?? index}
                                data-row={rowIndex}
                                data-index={index}
                                aria-label={`${row.name}, ${labels[index]}: ${STATUS_LABELS[status]}`}
                                className={cn(
                                    'h-5 flex-1 min-w-0 rounded-sm border',
                                    isLowEvidence(row, index) ? LOW_EVIDENCE_CLASSES : STATUS_CLASSES[status]
                                )}
                            />
                        ))}
                    </span>
                    <span className="w-24 @2xl:w-28 shrink-0 text-right tabular-nums truncate font-semibold">
                        {row.gradedCount === 0 ? (row.enabled ? 'No results' : 'Disabled') : compactHeadline(row)}
                    </span>
                </div>
            )),
        [statusGridRows, buckets, labels, evaluationUrl]
    )

    const hover = (event: MouseEvent<HTMLDivElement>): void => {
        const cell = (event.target as HTMLElement).closest<HTMLElement>('[data-row]')
        const grid = gridRef.current
        if (!cell || !grid) {
            setHovered(null)
            return
        }
        const row = Number(cell.dataset.row)
        const index = Number(cell.dataset.index)
        if (hovered?.row === row && hovered.index === index) {
            return
        }
        const cellBox = cell.getBoundingClientRect()
        const gridBox = grid.getBoundingClientRect()
        setHovered({
            row,
            index,
            box: {
                left: cellBox.left - gridBox.left,
                top: cellBox.top - gridBox.top,
                width: cellBox.width,
                height: cellBox.height,
            },
        })
    }

    const hoveredRow = hovered ? statusGridRows[hovered.row] : undefined

    return (
        <div className="flex flex-col gap-1 text-sm">
            <div className="flex items-center gap-3 text-xs text-secondary">
                <span className="w-28 @2xl:w-48 shrink-0" />
                <span className="flex-1 flex justify-between">
                    <span>{buckets.length ? formatBucket(buckets[0], interval, 'MMM D') : ''}</span>
                    <span>{buckets.length ? formatBucket(buckets[buckets.length - 1], interval, 'MMM D') : ''}</span>
                </span>
                <span className="w-24 @2xl:w-28 shrink-0 text-right">Result</span>
            </div>
            <div
                ref={gridRef}
                className="relative flex flex-col gap-1"
                onMouseOver={hover}
                onMouseLeave={() => setHovered(null)}
            >
                {rows}
                {hovered && hoveredRow && (
                    <Tooltip
                        // A new anchor per cell, because the tooltip does not follow an anchor that moves.
                        key={`${hovered.row}-${hovered.index}`}
                        visible
                        title={
                            <>
                                <div className="font-semibold">{`${hoveredRow.name}, ${labels[hovered.index]}`}</div>
                                <div>{describeBucket(hoveredRow, hovered.index)}</div>
                                <div>
                                    {isLowEvidence(hoveredRow, hovered.index)
                                        ? 'Too few results to compare'
                                        : STATUS_LABELS[hoveredRow.bucketStatus[hovered.index]]}
                                </div>
                            </>
                        }
                    >
                        <span
                            className="absolute pointer-events-none"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={hovered.box}
                        />
                    </Tooltip>
                )}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 pt-2 text-xs text-secondary">
                {LEGEND_ORDER.map((status) => (
                    <span key={status} className="inline-flex items-center gap-1.5">
                        <span className={cn('inline-block size-3 rounded-sm border', STATUS_CLASSES[status])} />
                        <span>{STATUS_LABELS[status]}</span>
                    </span>
                ))}
                <span className="inline-flex items-center gap-1.5">
                    <span className={cn('inline-block size-3 rounded-sm border', LOW_EVIDENCE_CLASSES)} />
                    <span>Too few results to compare</span>
                </span>
            </div>
        </div>
    )
}
