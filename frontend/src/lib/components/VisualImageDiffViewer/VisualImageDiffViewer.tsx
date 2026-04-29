import { useEffect, useMemo, useRef, useState } from 'react'

import { LemonSegmentedButton, LemonSlider, LemonSwitch, LemonTag, type LemonTagType } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export type VisualDiffResult = 'changed' | 'new' | 'removed' | 'unchanged'

export type ComparisonMode = 'sideBySide' | 'blend' | 'split' | 'diff'

export interface VisualImageDiffViewerProps {
    baselineUrl: string | null
    currentUrl: string | null
    diffUrl: string | null
    diffPercentage: number | null
    result: VisualDiffResult
    className?: string
    /** Natural image width — images under 600px on both axes render at 2x with pixelated scaling */
    imageWidth?: number
    imageHeight?: number
    mode?: ComparisonMode
    onModeChange?: (mode: ComparisonMode) => void
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
    imgClassName?: string
    imgStyle?: React.CSSProperties
}

function ImagePanel({ url, label, emptyTitle, imgClassName, imgStyle }: ImagePanelProps): JSX.Element {
    return (
        <div className="overflow-hidden rounded-lg border bg-bg-light inline-block max-w-full">
            <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide border-b bg-bg-3000">
                {label}
            </div>
            {url ? (
                <img
                    src={url}
                    alt={label}
                    loading="lazy"
                    decoding="async"
                    className={cn('h-auto bg-black/5', imgClassName || 'max-w-full')}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={imgStyle}
                />
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

/** Images smaller than this threshold render at 2x with pixelated scaling */
const SMALL_IMAGE_THRESHOLD = 600

function effectiveMode(requested: ComparisonMode, supportsComparison: boolean, hasDiffImage: boolean): ComparisonMode {
    if (!supportsComparison) {
        return 'blend'
    }
    if (!hasDiffImage && requested === 'diff') {
        return 'blend'
    }
    return requested
}

export function VisualImageDiffViewer({
    baselineUrl,
    currentUrl,
    diffUrl,
    diffPercentage,
    result,
    className,
    imageWidth,
    imageHeight,
    mode: controlledMode,
    onModeChange,
}: VisualImageDiffViewerProps): JSX.Element {
    const supportsComparison = isComparisonResult(result)
    const hasBothImages = Boolean(baselineUrl && currentUrl)
    const hasDiffImage = Boolean(diffUrl)
    const isSmallImage =
        imageWidth !== undefined &&
        imageWidth < SMALL_IMAGE_THRESHOLD &&
        (imageHeight === undefined || imageHeight < SMALL_IMAGE_THRESHOLD)
    const pixelatedStyle = isSmallImage
        ? { imageRendering: 'pixelated' as const, width: (imageWidth ?? 0) * 2, maxWidth: '100%' }
        : {}
    const pixelatedClass = isSmallImage ? '' : 'max-w-full'

    const [internalMode, setInternalMode] = useState<ComparisonMode>('sideBySide')
    const requestedMode = controlledMode ?? internalMode
    const mode: ComparisonMode = effectiveMode(requestedMode, supportsComparison, hasDiffImage)
    const setMode = (newMode: ComparisonMode): void => {
        setInternalMode(newMode)
        onModeChange?.(newMode)
    }
    const [splitPosition, setSplitPosition] = useState(25)
    const [blendPercentage, setBlendPercentage] = useState(50)
    const [showDiffOverlay, setShowDiffOverlay] = useState(false)
    const [diffOverlayOpacity, setDiffOverlayOpacity] = useState(55)
    const [flicker, setFlicker] = useState(false)
    const [flickerCurrentVisible, setFlickerCurrentVisible] = useState(false)
    const [draggingSplit, setDraggingSplit] = useState(false)
    const overlayRef = useRef<HTMLDivElement | null>(null)

    const diffLabel = formatDiffPercentage(diffPercentage)

    const comparisonModes = useMemo(() => {
        const modes: { value: ComparisonMode; label: string; 'data-attr': string }[] = [
            { value: 'sideBySide', label: 'Side by side', 'data-attr': 'image-diff-mode-side-by-side' },
            { value: 'blend', label: 'Blend', 'data-attr': 'image-diff-mode-blend' },
            { value: 'split', label: 'Split', 'data-attr': 'image-diff-mode-split' },
        ]
        if (hasDiffImage) {
            modes.push({ value: 'diff', label: 'Diff', 'data-attr': 'image-diff-mode-diff' })
        }
        return modes
    }, [hasDiffImage])

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
                <div className="p-3 flex justify-center">
                    <ImagePanel url={diffUrl} label="Diff" emptyTitle="No diff image available" />
                </div>
            )
        }

        if (mode === 'sideBySide') {
            return (
                <div className="flex flex-col gap-3 p-3 lg:flex-row lg:justify-center lg:items-start">
                    <ImagePanel
                        url={baselineUrl}
                        label="Before"
                        emptyTitle="Before snapshot missing"
                        imgClassName={pixelatedClass}
                        imgStyle={pixelatedStyle}
                    />
                    <ImagePanel
                        url={currentUrl}
                        label="After"
                        emptyTitle="After snapshot missing"
                        imgClassName={pixelatedClass}
                        imgStyle={pixelatedStyle}
                    />
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
            <div className="p-3 flex justify-center">
                <div
                    className="overflow-hidden rounded-lg border bg-bg-light inline-block max-w-full relative"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={isSmallImage ? { width: (imageWidth ?? 0) * 2, maxWidth: '100%' } : undefined}
                >
                    {/* Base header — blend: both labels; split: "Before" left-aligned */}
                    <div className="flex items-center justify-between px-2 py-1 border-b bg-bg-3000 text-[11px] font-semibold uppercase tracking-wide">
                        {mode === 'blend' ? (
                            <>
                                <span>Before</span>
                                <span className="font-normal normal-case tracking-normal tabular-nums text-muted">
                                    {100 - blendPercentage}% / {blendPercentage}%
                                </span>
                                <span>After</span>
                            </>
                        ) : (
                            <span>Before</span>
                        )}
                    </div>

                    {/* Base image area */}
                    <div ref={overlayRef} className="relative overflow-hidden">
                        {baselineUrl ? (
                            <img
                                src={baselineUrl}
                                alt="Before snapshot"
                                className="w-full h-auto bg-black/5 block"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={isSmallImage ? { imageRendering: 'pixelated' as const } : undefined}
                            />
                        ) : (
                            <EmptyImageState title="Before snapshot missing" />
                        )}

                        {/* Flicker overlay — full image swap inside image area */}
                        {flicker && mode === 'split' && activeOverlayUrl && (
                            <div className="absolute top-0 left-0 w-full h-full overflow-hidden">
                                <img
                                    src={activeOverlayUrl}
                                    alt="Flicker frame"
                                    className="w-full h-auto bg-black/5 block"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={isSmallImage ? { imageRendering: 'pixelated' as const } : undefined}
                                />
                            </div>
                        )}

                        {/* Blend overlay — inside image area only */}
                        {mode === 'blend' && activeOverlayUrl && (
                            <div
                                className="absolute top-0 left-0 w-full h-full overflow-hidden"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    opacity: !flicker ? Math.max(0, Math.min(1, blendPercentage / 100)) : 1,
                                }}
                            >
                                <img
                                    src={activeOverlayUrl}
                                    alt="After snapshot"
                                    className="w-full h-auto bg-black/5 block"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={isSmallImage ? { imageRendering: 'pixelated' as const } : undefined}
                                />
                            </div>
                        )}

                        {showDiffOverlay && hasDiffImage && (
                            <img
                                src={diffUrl as string}
                                alt="Diff overlay"
                                className="absolute top-0 left-0 w-full h-auto mix-blend-screen pointer-events-none"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ opacity: diffOverlayOpacity / 100 }}
                            />
                        )}

                        {/* Split drag handle — inside image area */}
                        {!flicker && mode === 'split' && hasBothImages && (
                            <button
                                type="button"
                                className="absolute inset-y-0 z-30 w-8 -translate-x-1/2 cursor-col-resize focus:outline-none"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ left: `${splitPosition}%` }}
                                onMouseDown={(event) => {
                                    event.preventDefault()
                                    setDraggingSplit(true)
                                }}
                                onTouchStart={() => setDraggingSplit(true)}
                                aria-label="Drag comparison split handle"
                            >
                                <div className="absolute left-1/2 top-1/2 flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border bg-surface-primary text-xs shadow-sm">
                                    ⇆
                                </div>
                            </button>
                        )}
                    </div>

                    {/* Split overlay — spans header + image, clipped from the left at split position */}
                    {mode === 'split' && !flicker && activeOverlayUrl && (
                        <div
                            className="absolute inset-0 z-10 overflow-hidden pointer-events-none"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ clipPath: `inset(0 0 0 ${splitPosition}%)` }}
                        >
                            <div className="flex items-center justify-end px-2 py-1 border-b bg-bg-3000 text-[11px] font-semibold uppercase tracking-wide">
                                <span>After</span>
                            </div>
                            <img
                                src={activeOverlayUrl}
                                alt="After snapshot"
                                className="w-full h-auto bg-black/5 block"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={isSmallImage ? { imageRendering: 'pixelated' as const } : undefined}
                            />
                        </div>
                    )}

                    {/* Split divider line + shadow — spans full height including header */}
                    {!flicker && mode === 'split' && hasBothImages && (
                        <>
                            <div
                                className="absolute inset-y-0 z-20 w-px bg-border-bold pointer-events-none"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ left: `${splitPosition}%` }}
                            />
                            <div
                                className="absolute inset-y-0 z-20 w-3 -translate-x-full pointer-events-none"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    left: `${splitPosition}%`,
                                    background: 'linear-gradient(to left, rgba(0,0,0,0.15), transparent)',
                                }}
                            />
                        </>
                    )}
                </div>
            </div>
        )
    }

    const renderSingleImageBody = (): JSX.Element => {
        const singleImage =
            result === 'new' ? currentUrl : result === 'removed' ? baselineUrl : currentUrl || baselineUrl || diffUrl
        const singleLabel = result === 'new' ? 'New snapshot' : 'Before snapshot'
        const emptyTitle =
            result === 'new' ? 'New snapshot is missing an image' : 'Removed snapshot has no before image'

        return (
            <div className="p-3 flex justify-center">
                <ImagePanel
                    url={singleImage}
                    label={singleLabel}
                    emptyTitle={emptyTitle}
                    imgClassName={pixelatedClass}
                    imgStyle={pixelatedStyle}
                />
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
                        {isSmallImage && (
                            <LemonTag type="highlight" className="font-bold">
                                Enlarged 2x for review
                            </LemonTag>
                        )}
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
                                <span className="text-xs text-muted-foreground whitespace-nowrap">Before → After</span>
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
