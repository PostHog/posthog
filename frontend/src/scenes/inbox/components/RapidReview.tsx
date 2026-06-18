import { useActions, useValues } from 'kea'
import { animate, motion, useMotionValue, useTransform } from 'motion/react'
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'

import { IconArchive, IconArrowLeft, IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { rapidReviewLogic } from '../logics/rapidReviewLogic'
import { SignalReport } from '../types'
import { ReportDetail } from './detail/ReportDetail'

/** Drag distance / velocity past which a release commits the swipe. */
const SWIPE_DISTANCE_THRESHOLD = 140
const SWIPE_VELOCITY_THRESHOLD = 600

type SwipeDirection = 'left' | 'right'

interface SwipeSheetHandle {
    swipe: (direction: SwipeDirection) => void
}

/** A draggable, internally-scrollable sheet rendering the full report detail. */
const SwipeSheet = forwardRef<SwipeSheetHandle, { report: SignalReport; onResolved: (d: SwipeDirection) => void }>(
    function SwipeSheet({ report, onResolved }, ref): JSX.Element {
        const x = useMotionValue(0)
        const rotate = useTransform(x, [-400, 0, 400], [-6, 0, 6])
        const archiveOpacity = useTransform(x, [-SWIPE_DISTANCE_THRESHOLD, -40], [1, 0])
        const mergeOpacity = useTransform(x, [40, SWIPE_DISTANCE_THRESHOLD], [0, 1])

        const fling = (direction: SwipeDirection): void => {
            animate(x, direction === 'right' ? 1200 : -1200, {
                duration: 0.35,
                ease: 'easeIn',
                onComplete: () => onResolved(direction),
            })
        }

        useImperativeHandle(ref, () => ({ swipe: fling }))

        return (
            <motion.div
                className="absolute inset-0 flex justify-center"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ x, rotate }}
                drag="x"
                dragDirectionLock
                dragSnapToOrigin
                dragElastic={0.5}
                onDragEnd={(_, info) => {
                    if (info.offset.x > SWIPE_DISTANCE_THRESHOLD || info.velocity.x > SWIPE_VELOCITY_THRESHOLD) {
                        fling('right')
                    } else if (
                        info.offset.x < -SWIPE_DISTANCE_THRESHOLD ||
                        info.velocity.x < -SWIPE_VELOCITY_THRESHOLD
                    ) {
                        fling('left')
                    }
                }}
            >
                <div className="relative w-full max-w-3xl h-full rounded-lg border border-primary bg-surface-primary shadow-sm overflow-hidden">
                    {/* Swipe-intent stamps, pinned over the scroll area. */}
                    <motion.div
                        className="absolute top-6 left-6 z-10 flex items-center gap-1 rounded-md border-2 border-danger px-3 py-1.5 text-base font-bold uppercase text-danger -rotate-12 pointer-events-none"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ opacity: archiveOpacity }}
                    >
                        <IconArchive className="size-5" /> Archive
                    </motion.div>
                    <motion.div
                        className="absolute top-6 right-6 z-10 flex items-center gap-1 rounded-md border-2 border-success px-3 py-1.5 text-base font-bold uppercase text-success rotate-12 pointer-events-none"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ opacity: mergeOpacity }}
                    >
                        <IconCheckCircle className="size-5" /> Merge
                    </motion.div>
                    <div className="size-full overflow-y-auto overscroll-contain">
                        <ReportDetail report={report} tab="pulls" />
                    </div>
                </div>
            </motion.div>
        )
    }
)

export function RapidReview({ onExit }: { onExit: () => void }): JSX.Element {
    const { currentReport, remainingCount, isLoaded, reportsResponseLoading } = useValues(rapidReviewLogic)
    const { archiveCurrent, mergeCurrent } = useActions(rapidReviewLogic)
    const sheetRef = useRef<SwipeSheetHandle>(null)

    const onResolved = (direction: SwipeDirection): void => {
        if (direction === 'right') {
            mergeCurrent()
        } else {
            archiveCurrent()
        }
    }

    // Keyboard shortcuts: ←  archive, →  merge. Active only while a sheet is present.
    useEffect(() => {
        if (!currentReport) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'ArrowLeft') {
                sheetRef.current?.swipe('left')
            } else if (event.key === 'ArrowRight') {
                sheetRef.current?.swipe('right')
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [currentReport])

    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="flex items-center justify-between gap-2 px-6 pt-4 pb-3 shrink-0">
                <LemonButton type="secondary" size="small" icon={<IconArrowLeft />} onClick={onExit}>
                    Back to list
                </LemonButton>
                {currentReport && (
                    <span className="text-xs text-tertiary tabular-nums">
                        {remainingCount} to review · ← archive · → merge
                    </span>
                )}
            </div>

            {!isLoaded && reportsResponseLoading ? (
                <div className="flex flex-1 items-center justify-center px-4 pb-4 min-h-0">
                    <LemonSkeleton className="w-full max-w-3xl h-full rounded-lg" />
                </div>
            ) : !currentReport ? (
                <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center px-6">
                    <IconCheckCircle className="text-4xl text-success" />
                    <h3 className="m-0 text-base font-semibold">All caught up</h3>
                    <p className="text-sm text-secondary max-w-sm">
                        No more pull requests to review. New PR drafts will appear here as agents ship changes.
                    </p>
                </div>
            ) : (
                <>
                    {/* Deck fills the remaining height; the sheet scrolls internally. */}
                    <div className="relative flex-1 min-h-0 px-4">
                        {/* A faint backing sheet suggests the stack. */}
                        <div className="absolute inset-x-4 inset-y-0 flex justify-center pointer-events-none">
                            <div className="w-full max-w-3xl h-full scale-[0.97] translate-y-2 rounded-lg border border-primary bg-surface-primary opacity-50" />
                        </div>
                        <SwipeSheet
                            key={currentReport.id}
                            ref={sheetRef}
                            report={currentReport}
                            onResolved={onResolved}
                        />
                    </div>

                    <div className="flex items-center justify-center gap-6 py-4 shrink-0">
                        <LemonButton
                            type="secondary"
                            status="danger"
                            icon={<IconArchive />}
                            tooltip="Archive (←)"
                            onClick={() => sheetRef.current?.swipe('left')}
                            aria-label="Archive"
                        >
                            Archive
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            icon={<IconCheckCircle />}
                            tooltip="Merge into GitHub (→)"
                            onClick={() => sheetRef.current?.swipe('right')}
                            aria-label="Merge"
                        >
                            Merge
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
