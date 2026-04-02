import { useEffect, useMemo, useRef, useState } from 'react'

import { LemonSegmentedButton, LemonSlider, LemonSwitch, LemonTag, type LemonTagType } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export type VisualDiffResult = 'changed' | 'new' | 'removed' | 'unchanged'

type ComparisonMode = 'sideBySide' | 'blend' | 'split' | 'diff'

export interface VisualImageDiffViewerProps {
    baselineUrl: string | null
    currentUrl: string | null
    diffUrl: string | null
    diffPercentage: number | null
    result: VisualDiffResult
    className?: string
}

const RESULT_LABELS: Record<VisualDiffResult, string> = {
    changed: 'Changed',
    new: 'New',
    removed: 'Removed',
    unchanged: 'Unchanged',
}

const RESULT_TAG_TYPES: Record<VisualDiffResult, LemonTagType> = {
    changed: 'warning',
    new: 'primary',
    removed: 'danger',
    unchanged: 'success',
}

function isComparisonResult(result: VisualDiffResult): boolean {
    return result === 'changed' || result === 'unchanged'
}

function formatDiffPercentage(diffPercentage: number | null): string | null {
    if (diffPercentage === null || Number.isNaN(diffPercentage)) {
        return null
    }
    const decimals = Math.abs(diffPercentage) < 10 ? 2 : 1
    return `${Math.abs(diffPercentage).toFixed(decimals)}% different`
}

interface ImagePanelProps {
    url: string | null
    label: string
    emptyTitle: string
}

function ImagePanel({ url, label, emptyTitle }: ImagePanelProps): JSX.Element {
    return (
        <div className="relative overflow-hidden rounded-lg border bg-bg-light">
            <div className="absolute top-2 left-2 z-10 rounded-md border bg-surface-primary/90 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide">
                {label}
            </div>
            {url ? (
                <img src={url} alt={label} className="max-w-full bg-black/5" />
            ) : (
                <EmptyImageState title={emptyTitle} />
            )}
        </div>
    )
}

function EmptyImageState({ title }: { title: string }): JSX.Element {
    return (
        <div className="flex size-full items-center justify-center bg-bg-light px-4 text-center text-muted-foreground">
            <div>
                <div className="text-sm font-semibold">{title}</div>
                <div className="text-xs mt-1">No image available</div>
            </div>
        </div>
    )
}

export function VisualImageDiffViewer({
    baselineUrl,
    currentUrl,
    diffUrl,
    diffPercentage,
    result,
    className,
}: VisualImageDiffViewerProps): JSX.Element {
    const supportsComparison = isComparisonResult(result)
    const hasBothImages = Boolean(baselineUrl && currentUrl)
    const hasDiffImage = Boolean(diffUrl)

    const [mode, setMode] = useState<ComparisonMode>('sideBySide')
    const [splitPosition, setSplitPosition] = useState(50)
    const [blendPercentage, setBlendPercentage] = useState(50)
    const [showDiffOverlay, setShowDiffOverlay] = useState(false)
    const [diffOverlayOpacity, setDiffOverlayOpacity] = useState(55)
    const [flicker, setFlicker] = useState(false)
    const [flickerCurrentVisible, setFlickerCurrentVisible] = useState(false)
    const [draggingSplit, setDraggingSplit] = useState(false)
    const overlayRef = useRef<HTMLDivElement | null>(null)

    const diffLabel = formatDiffPercentage(diffPercentage)

    const comparisonModes = useMemo(() => {
        const modes: { value: ComparisonMode; label: string }[] = [
            { value: 'sideBySide', label: 'Side by side' },
            { value: 'blend', label: 'Blend' },
            { value: 'split', label: 'Split' },
        ]
        if (hasDiffImage) {
            modes.push({ value: 'diff', label: 'Diff' })
        }
        return modes
    }, [hasDiffImage])

    useEffect(() => {
        if (!supportsComparison) {
            setMode('blend')
            return
        }
        if (!hasDiffImage && mode === 'diff') {
            setMode('blend')
        }
    }, [supportsComparison, hasDiffImage, mode])

    useEffect(() => {
        if (!(flicker && mode === 'split' && result === 'changed' && hasBothImages)) {
            setFlickerCurrentVisible(false)
            return
        }
        const interval = window.setInterval(() => {
            setFlickerCurrentVisible((current) => !current)
        }, 650)
        return () => {
            window.clearInterval(interval)
        }
    }, [flicker, mode, result, hasBothImages])

    useEffect(() => {
        if (mode !== 'split' || !hasBothImages) {
            setFlicker(false)
        }
    }, [mode, hasBothImages])

    useEffect(() => {
        if (!draggingSplit) {
            return
        }

        const setSplitFromClientX = (clientX: number): void => {
            if (!overlayRef.current) {
                return
            }
            const rect = overlayRef.current.getBoundingClientRect()
            if (rect.width <= 0) {
                return
            }
            const next = ((clientX - rect.left) / rect.width) * 100
            setSplitPosition(Math.max(0, Math.min(100, next)))
        }

        const handleMouseMove = (event: MouseEvent): void => {
            setSplitFromClientX(event.clientX)
        }
        const handleTouchMove = (event: TouchEvent): void => {
            if (event.touches.length > 0) {
                setSplitFromClientX(event.touches[0].clientX)
            }
        }
        const stopDragging = (): void => {
            setDraggingSplit(false)
        }

        window.addEventListener('mousemove', handleMouseMove)
        window.addEventListener('mouseup', stopDragging)
        window.addEventListener('touchmove', handleTouchMove, { passive: true })
        window.addEventListener('touchend', stopDragging)

        return () => {
            window.removeEventListener('mousemove', handleMouseMove)
            window.removeEventListener('mouseup', stopDragging)
            window.removeEventListener('touchmove', handleTouchMove)
            window.removeEventListener('touchend', stopDragging)
        }
    }, [draggingSplit])

    const renderComparisonBody = (): JSX.Element => {
        if (mode === 'diff') {
            return (
                <div className="p-3">
                    <ImagePanel url={diffUrl} label="Diff" emptyTitle="No diff image available" />
                </div>
            )
        }

        if (mode === 'sideBySide') {
            return (
                <div className="grid grid-cols-1 gap-3 p-3 lg:grid-cols-2">
                    <ImagePanel url={baselineUrl} label="Baseline" emptyTitle="Baseline snapshot missing" />
                    <ImagePanel url={currentUrl} label="Current" emptyTitle="Current snapshot missing" />
                </div>
            )
        }

        const activeOverlayUrl =
            flicker && mode === 'split' && hasBothImages
                ? flickerCurrentVisible
                    ? currentUrl
                    : baselineUrl
                : currentUrl

        return (
            <div className="p-3">
                <div ref={overlayRef} className="relative overflow-hidden rounded-lg border bg-bg-light aspect-[16/10]">
                    {baselineUrl ? (
                        <img
                            src={baselineUrl}
                            alt="Baseline snapshot"
                            className={cn('absolute inset-0 size-full object-contain bg-black/5')}
                        />
                    ) : (
                        <EmptyImageState title="Baseline snapshot missing" />
                    )}

                    {activeOverlayUrl && (
                        <div
                            className="absolute inset-0 overflow-hidden"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                clipPath:
                                    mode === 'split' && !flicker ? `inset(0 ${100 - splitPosition}% 0 0)` : undefined,
                                opacity:
                                    mode === 'blend' && !flicker ? Math.max(0, Math.min(1, blendPercentage / 100)) : 1,
                            }}
                        >
                            <img
                                src={activeOverlayUrl}
                                alt="Current snapshot"
                                className="size-full object-contain bg-black/5"
                            />
                        </div>
                    )}

                    {showDiffOverlay && hasDiffImage && (
                        <img
                            src={diffUrl as string}
                            alt="Diff overlay"
                            className="absolute inset-0 size-full object-contain mix-blend-screen pointer-events-none"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ opacity: diffOverlayOpacity / 100 }}
                        />
                    )}

                    {!flicker && mode === 'split' && hasBothImages && (
                        <button
                            type="button"
                            className="absolute inset-y-0 z-20 w-8 -translate-x-1/2 cursor-col-resize focus:outline-none"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: `${splitPosition}%` }}
                            onMouseDown={(event) => {
                                event.preventDefault()
                                setDraggingSplit(true)
                            }}
                            onTouchStart={() => setDraggingSplit(true)}
                            aria-label="Drag comparison split handle"
                        >
                            <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border-bold" />
                            <div className="absolute left-1/2 top-1/2 flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border bg-surface-primary text-xs shadow-sm">
                                ⇆
                            </div>
                        </button>
                    )}

                    <div className="absolute top-2 left-2 rounded-md border bg-surface-primary/90 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide">
                        Baseline
                    </div>
                    <div className="absolute top-2 right-2 rounded-md border bg-surface-primary/90 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide">
                        Current
                    </div>
                    {mode === 'blend' && (
                        <div className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-md border bg-surface-primary/90 px-2 py-1 text-[11px] font-semibold tabular-nums">
                            Baseline {100 - blendPercentage}% · Current {blendPercentage}%
                        </div>
                    )}
                </div>
            </div>
        )
    }

    const renderSingleImageBody = (): JSX.Element => {
        const singleImage =
            result === 'new' ? currentUrl : result === 'removed' ? baselineUrl : currentUrl || baselineUrl || diffUrl
        const singleLabel = result === 'new' ? 'Current snapshot' : 'Baseline snapshot'
        const emptyTitle =
            result === 'new' ? 'New snapshot is missing an image' : 'Removed snapshot has no baseline image'

        return (
            <div className="p-3">
                <ImagePanel url={singleImage} label={singleLabel} emptyTitle={emptyTitle} />
            </div>
        )
    }

    return (
        <section className={cn('overflow-hidden rounded-xl border bg-surface-primary shadow-sm', className)}>
            <div className="border-b bg-gradient-to-r from-bg-light via-bg-light to-bg-light/70 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonTag type={RESULT_TAG_TYPES[result]}>{RESULT_LABELS[result]}</LemonTag>
                        {diffLabel && <LemonTag type="muted">{diffLabel}</LemonTag>}
                    </div>
                    {supportsComparison && (
                        <LemonSegmentedButton
                            size="small"
                            value={mode}
                            onChange={(newMode) => setMode(newMode)}
                            options={comparisonModes}
                        />
                    )}
                </div>

                {supportsComparison && mode !== 'sideBySide' && mode !== 'diff' && (
                    <div className="mt-3 flex flex-wrap items-center gap-4 rounded-lg border bg-surface-primary px-3 py-2">
                        {mode === 'split' && hasBothImages && (
                            <LemonSwitch checked={flicker} onChange={setFlicker} size="small" label="Flicker" />
                        )}
                        {mode === 'blend' && (
                            <div className="flex min-w-60 flex-1 items-center gap-3">
                                <span className="text-xs text-muted-foreground whitespace-nowrap">Old → New</span>
                                <LemonSlider
                                    min={0}
                                    max={100}
                                    step={1}
                                    value={blendPercentage}
                                    onChange={setBlendPercentage}
                                    className="m-0 w-full"
                                />
                                <span className="text-xs tabular-nums text-muted-foreground w-10 text-right">
                                    {blendPercentage}%
                                </span>
                            </div>
                        )}
                        {hasDiffImage && (
                            <>
                                <LemonSwitch
                                    checked={showDiffOverlay}
                                    onChange={setShowDiffOverlay}
                                    size="small"
                                    label="Diff overlay"
                                />
                                <div
                                    className={cn(
                                        'flex min-w-60 flex-1 items-center gap-3 transition-opacity',
                                        showDiffOverlay ? 'opacity-100' : 'opacity-40 pointer-events-none'
                                    )}
                                    aria-hidden={!showDiffOverlay}
                                >
                                    <span className="text-xs text-muted-foreground whitespace-nowrap">
                                        Overlay opacity
                                    </span>
                                    <LemonSlider
                                        min={0}
                                        max={100}
                                        step={1}
                                        value={diffOverlayOpacity}
                                        onChange={setDiffOverlayOpacity}
                                        className="m-0 w-full"
                                    />
                                    <span className="text-xs tabular-nums text-muted-foreground w-10 text-right">
                                        {diffOverlayOpacity}%
                                    </span>
                                </div>
                            </>
                        )}
                    </div>
                )}
            </div>

            {supportsComparison ? renderComparisonBody() : renderSingleImageBody()}
        </section>
    )
}
