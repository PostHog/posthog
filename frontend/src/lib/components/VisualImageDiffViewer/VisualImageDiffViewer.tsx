import { useEffect, useMemo, useRef, useState } from 'react'

import { LemonSegmentedButton, LemonSlider, LemonSwitch, LemonTag, type LemonTagType } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export type VisualDiffResult = 'changed' | 'new' | 'removed' | 'unchanged'

export type ComparisonMode = 'sideBySide' | 'blend' | 'split' | 'diff'

/** Bounding box of a connected diff region, in natural image coordinates. */
export interface DiffOverlayBox {
    x: number
    y: number
    width: number
    height: number
}

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
    /**
     * Bounding boxes drawn over the diff image (and the blend overlay
     * when on `blend` mode). Coords are in the diff image's natural
     * pixel space (which is the *padded* size when baseline and current
     * differed); the overlay scales with the rendered image via SVG
     * viewBox + preserveAspectRatio="none". Empty array == no overlays.
     */
    diffOverlayBoxes?: DiffOverlayBox[]
    /**
     * Natural-pixel dimensions of the bbox coord space — the diff
     * image's dimensions, which equal current/baseline when sizes
     * match and the padded size when they don't. Defaults to
     * `imageWidth`/`imageHeight` for back-compat with callers that
     * never had a size mismatch.
     */
    diffOverlayWidth?: number
    diffOverlayHeight?: number
    /** Highlighted cluster index — emphasized in the overlay (filled, opaque). */
    highlightedOverlayIndex?: number | null
    /** Fires when a user hovers a bbox/number in the overlay. Lets the
     *  parent sync a sidebar panel's row highlight to the overlay. */
    onOverlayHover?: (index: number | null) => void
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
    /** When set, draw bbox outlines over the image at these natural-coord positions. */
    overlayBoxes?: DiffOverlayBox[]
    overlayWidth?: number
    overlayHeight?: number
    /** Highlighted cluster index — that one box renders emphasized. */
    highlightedOverlayIndex?: number | null
    /** Fires on hover so a parent panel can sync. */
    onOverlayHover?: (index: number | null) => void
}

function ImagePanel({
    url,
    label,
    emptyTitle,
    imgClassName,
    imgStyle,
    overlayBoxes,
    overlayWidth,
    overlayHeight,
    highlightedOverlayIndex,
    onOverlayHover,
}: ImagePanelProps): JSX.Element {
    const hasOverlay = !!url && !!overlayBoxes && overlayBoxes.length > 0 && !!overlayWidth && !!overlayHeight
    return (
        <div className="overflow-hidden rounded-lg border bg-bg-light inline-block max-w-full">
            <div className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide border-b bg-bg-3000">
                {label}
            </div>
            {url ? (
                // `block` on the inline-block wrapper kills the implicit
                // baseline-descender gap that nudges the SVG overlay a few
                // pixels below the image's actual bottom edge.
                <div className="relative inline-block max-w-full leading-none">
                    <img
                        src={url}
                        alt={label}
                        loading="lazy"
                        decoding="async"
                        className={cn('block h-auto bg-black/5', imgClassName || 'max-w-full')}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={imgStyle}
                    />
                    {hasOverlay && (
                        <BboxOverlay
                            boxes={overlayBoxes!}
                            width={overlayWidth!}
                            height={overlayHeight!}
                            highlightedIndex={highlightedOverlayIndex ?? null}
                            onHover={onOverlayHover}
                        />
                    )}
                </div>
            ) : (
                <EmptyImageState title={emptyTitle} />
            )}
        </div>
    )
}

interface BboxOverlayProps {
    boxes: DiffOverlayBox[]
    /** Natural pixel coord space the bboxes live in. */
    width: number
    height: number
    /** When non-null, that box is emphasized (filled) and the others fade. */
    highlightedIndex: number | null
    /** Fires on hover so the parent can sync sidebar highlight. */
    onHover?: (index: number | null) => void
}

// Warm orange palette to match the mockup — distinct from the
// blue-tinted "Before/After" labels and the green/red of result tags.
const OVERLAY_STROKE = 'rgb(245, 134, 52)'
const OVERLAY_FILL_DEFAULT = 'rgba(245, 134, 52, 0.10)'
const OVERLAY_FILL_HIGHLIGHT = 'rgba(245, 134, 52, 0.28)'

function BboxOverlay({ boxes, width, height, highlightedIndex, onHover }: BboxOverlayProps): JSX.Element {
    return (
        <>
            <svg
                // viewBox in the bbox coord space + preserveAspectRatio=none
                // stretches the SVG to the rendered image's box. With
                // `vector-effect: non-scaling-stroke` the stroke stays a
                // constant 2px regardless of how the image is scaled. The
                // SVG itself stays pointer-events-none so the rects don't
                // shadow underlying interactions; rects flip to auto so
                // they can fire hover callbacks for sidebar sync.
                className="absolute inset-0 w-full h-full pointer-events-none"
                viewBox={`0 0 ${width} ${height}`}
                preserveAspectRatio="none"
            >
                {boxes.map((b, i) => {
                    const isHighlighted = highlightedIndex === i
                    const isDimmed = highlightedIndex !== null && !isHighlighted
                    return (
                        <rect
                            key={i}
                            x={b.x}
                            y={b.y}
                            width={b.width}
                            height={b.height}
                            fill={isHighlighted ? OVERLAY_FILL_HIGHLIGHT : OVERLAY_FILL_DEFAULT}
                            stroke={OVERLAY_STROKE}
                            strokeWidth={isHighlighted ? 3 : 2}
                            strokeDasharray={isHighlighted ? undefined : '4 3'}
                            opacity={isDimmed ? 0.4 : 1}
                            vectorEffect="non-scaling-stroke"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                pointerEvents: onHover ? 'auto' : 'none',
                                cursor: onHover ? 'pointer' : undefined,
                            }}
                            onMouseEnter={onHover ? () => onHover(i) : undefined}
                            onMouseLeave={onHover ? () => onHover(null) : undefined}
                        />
                    )
                })}
            </svg>
            {boxes.map((b, i) => {
                const leftPct = (b.x / width) * 100
                const topPct = (b.y / height) * 100
                const isHighlighted = highlightedIndex === i
                const isDimmed = highlightedIndex !== null && !isHighlighted
                return (
                    <span
                        key={`label-${i}`}
                        className="absolute flex items-center justify-center rounded-full text-white text-[11px] font-bold tabular-nums shadow-md ring-1 ring-white/70 transition-transform"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            left: `calc(${leftPct}% - 11px)`,
                            top: `calc(${topPct}% - 11px)`,
                            width: 22,
                            height: 22,
                            background: OVERLAY_STROKE,
                            opacity: isDimmed ? 0.45 : 1,
                            transform: isHighlighted ? 'scale(1.15)' : undefined,
                            cursor: onHover ? 'pointer' : undefined,
                            pointerEvents: onHover ? 'auto' : 'none',
                        }}
                        onMouseEnter={onHover ? () => onHover(i) : undefined}
                        onMouseLeave={onHover ? () => onHover(null) : undefined}
                    >
                        {i + 1}
                    </span>
                )
            })}
        </>
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
    diffOverlayBoxes,
    diffOverlayWidth,
    diffOverlayHeight,
    highlightedOverlayIndex,
    onOverlayHover,
    mode: controlledMode,
    onModeChange,
}: VisualImageDiffViewerProps): JSX.Element {
    // Bbox coords live in the diff image's natural pixel space (= padded
    // size when sizes mismatched). Fall back to image dims for the
    // common matched-size case.
    const overlayCoordWidth = diffOverlayWidth ?? imageWidth
    const overlayCoordHeight = diffOverlayHeight ?? imageHeight
    const hasOverlayBoxes = !!diffOverlayBoxes && diffOverlayBoxes.length > 0
    const [showClusters, setShowClusters] = useState(true)
    const overlayBoxesIfShown = showClusters ? diffOverlayBoxes : undefined
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
                    <ImagePanel
                        url={diffUrl}
                        label="Diff"
                        emptyTitle="No diff image available"
                        overlayBoxes={overlayBoxesIfShown}
                        overlayWidth={overlayCoordWidth}
                        overlayHeight={overlayCoordHeight}
                        highlightedOverlayIndex={highlightedOverlayIndex}
                        onOverlayHover={onOverlayHover}
                    />
                </div>
            )
        }

        if (mode === 'sideBySide') {
            // Overlay only on the "After" panel — that's the side users
            // judge against, and bboxes were computed against current.
            // Skip when the bbox coord space doesn't match the rendered
            // image (size-mismatch case).
            const overlaySafeOnAfter =
                !!overlayBoxesIfShown && overlayCoordWidth === imageWidth && overlayCoordHeight === imageHeight
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
                        overlayBoxes={overlaySafeOnAfter ? overlayBoxesIfShown : undefined}
                        overlayWidth={overlayCoordWidth}
                        overlayHeight={overlayCoordHeight}
                        highlightedOverlayIndex={highlightedOverlayIndex}
                        onOverlayHover={onOverlayHover}
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

                        {/* Cluster bbox overlays — drawn on top of the
                         * blend stack so users can read where the change
                         * regions are without leaving blend mode. Only
                         * meaningful when the bbox coord space matches
                         * the underlying image (mismatch case has bboxes
                         * in padded coords that don't align with either
                         * baseline or current). */}
                        {(mode === 'blend' || mode === 'split') &&
                            !!overlayBoxesIfShown &&
                            overlayBoxesIfShown.length > 0 &&
                            !!overlayCoordWidth &&
                            !!overlayCoordHeight &&
                            overlayCoordWidth === imageWidth &&
                            overlayCoordHeight === imageHeight && (
                                <BboxOverlay
                                    boxes={overlayBoxesIfShown}
                                    width={overlayCoordWidth}
                                    height={overlayCoordHeight}
                                    highlightedIndex={highlightedOverlayIndex ?? null}
                                    onHover={onOverlayHover}
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
                            <div className="relative">
                                <img
                                    src={activeOverlayUrl}
                                    alt="After snapshot"
                                    className="w-full h-auto bg-black/5 block"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={isSmallImage ? { imageRendering: 'pixelated' as const } : undefined}
                                />
                                {/* Second copy of the bbox overlay inside the
                                 * clipped After half so the boxes stay visible
                                 * regardless of where the user drags the split.
                                 * Forwards onHover so hovering a chip on the
                                 * After side still syncs with the sidebar
                                 * panel (without it the After-side bboxes were
                                 * silently non-interactive). */}
                                {!!overlayBoxesIfShown &&
                                    overlayBoxesIfShown.length > 0 &&
                                    !!overlayCoordWidth &&
                                    !!overlayCoordHeight &&
                                    overlayCoordWidth === imageWidth &&
                                    overlayCoordHeight === imageHeight && (
                                        <BboxOverlay
                                            boxes={overlayBoxesIfShown}
                                            width={overlayCoordWidth}
                                            height={overlayCoordHeight}
                                            highlightedIndex={highlightedOverlayIndex ?? null}
                                            onHover={onOverlayHover}
                                        />
                                    )}
                            </div>
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
                        {hasOverlayBoxes && (
                            <LemonSwitch
                                checked={showClusters}
                                onChange={setShowClusters}
                                size="xsmall"
                                label="Clusters"
                                bordered
                            />
                        )}
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
