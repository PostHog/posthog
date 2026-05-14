import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import christopheDvdSrc from 'public/concierge/christophe-dvd.png'
import envelopeBackSrc from 'public/concierge/envelope/envelope-back.png'
import envelopeStampSrc from 'public/concierge/envelope/envelope-stamp.png'
import fullEnvelopeSrc from 'public/concierge/envelope/full-envelope.png'
import letterFoldedSrc from 'public/concierge/envelope/letter-folded.png'
import letterUnfoldedSrc from 'public/concierge/envelope/letter-unfolded.png'
import hoggieQuillSrc from 'public/concierge/hoggie-quill.png'
import scrollParchmentSrc from 'public/concierge/scroll/scroll-parchment.png'
import scrollRollLeftSrc from 'public/concierge/scroll/scroll-roll-left.png'
import scrollRollRightSrc from 'public/concierge/scroll/scroll-roll-right.png'

import { Starfield } from './Starfield'
import { useDvdScreensaver } from './useDvdScreensaver'

type DeliveryMode = 'envelope' | 'scroll' | 'galactic' | 'csm'

interface ConciergePayload {
    body?: string
    call_to_action?: string
    notification_style?: string
}

function wizardCommandFor(notificationId: string): string {
    return `npx @posthog/wizard concierge --id=${notificationId}`
}

function modeForStyle(style: string | undefined): DeliveryMode {
    switch (style) {
        case 'scroll':
            return 'scroll'
        case 'galactic':
            return 'galactic'
        case 'csm':
            return 'csm'
        case 'envelope':
        default:
            return 'envelope'
    }
}

export interface ConciergeModalProps {
    isOpen: boolean
    onClose: () => void
    notificationId: string
    title?: string
    body?: string
}

function parsePayload(body: string | undefined): ConciergePayload {
    if (!body) {
        return {}
    }
    try {
        return JSON.parse(body) as ConciergePayload
    } catch {
        return { body }
    }
}

// -- Handwriting animation for scroll mode --
// The hoggie is rendered inline after the last visible character so it
// scrolls with the text and stays next to the last word when done.

interface HoggiePos {
    x: number
    y: number
    isWriting: boolean
}

function HandwrittenText({
    text,
    onHoggieUpdate,
}: {
    text: string
    onHoggieUpdate?: (pos: HoggiePos) => void
}): JSX.Element {
    const [visibleCount, setVisibleCount] = useState(0)
    const cursorRef = useRef<HTMLSpanElement>(null)

    useEffect(() => {
        setVisibleCount(0)
    }, [text])

    useEffect(() => {
        if (visibleCount >= text.length) {
            return
        }
        const delay = 25 + Math.random() * 30
        const timer = setTimeout(() => setVisibleCount((c) => c + 1), delay)
        return () => clearTimeout(timer)
    }, [visibleCount, text])

    // Auto-scroll and report cursor position relative to the parchment wrapper
    useEffect(() => {
        if (!cursorRef.current) {
            return
        }
        cursorRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        if (onHoggieUpdate) {
            // Get position relative to the parchment wrapper (closest .scroll-parchment-wrapper)
            const wrapper = cursorRef.current.closest('.scroll-parchment-wrapper')
            if (wrapper) {
                const wrapperRect = wrapper.getBoundingClientRect()
                const cursorRect = cursorRef.current.getBoundingClientRect()
                onHoggieUpdate({
                    x: cursorRect.left - wrapperRect.left + cursorRect.width,
                    y: cursorRect.top - wrapperRect.top,
                    isWriting: visibleCount < text.length,
                })
            }
        }
    }, [visibleCount, onHoggieUpdate, text.length])

    return (
        <div
            style={{
                fontFamily: "'Caveat', cursive",
                fontSize: 20,
                color: '#3B2B26',
                lineHeight: 1.5,
                whiteSpace: 'pre-wrap',
                textAlign: 'left',
            }}
        >
            {text.slice(0, visibleCount)}
            <span ref={cursorRef} className="inline-block w-0" />
        </div>
    )
}

// -- Envelope mode --

function EnvelopeMode({ message }: { message: string }): JSX.Element {
    const [phase, setPhase] = useState<'sealed' | 'stamp-peeling' | 'open' | 'letter-unfolded'>('sealed')

    useEffect(() => {
        const timers = [
            // 1. Sealed envelope with stamp
            // 2. Stamp peels off
            setTimeout(() => setPhase('stamp-peeling'), 550),
            // 3. Open envelope — crossfade to open state with folded letter
            setTimeout(() => setPhase('open'), 1400),
            // 4. Unfolded letter rises up on top
            setTimeout(() => setPhase('letter-unfolded'), 2100),
        ]
        return () => timers.forEach(clearTimeout)
    }, [])

    // All layers are 1600×1200 canvases — stack them inside a scaled-up
    // wrapper (like scroll mode) so the art fills the modal.
    const layerClass = 'absolute inset-0 w-full h-full object-contain pointer-events-none'

    return (
        <div className="relative w-full h-full overflow-hidden flex items-center justify-center">
            {/* Scaled wrapper — all layers live inside here */}
            <div
                className="relative"
                style={{
                    width: '130%',
                    height: '130%',
                    // keep aspect ratio of the 1600×1200 canvases
                    maxWidth: '130%',
                    maxHeight: '130%',
                }}
            >
                {/* Closed envelope — fades out as it transitions to open */}
                <motion.img
                    src={fullEnvelopeSrc}
                    alt=""
                    className={layerClass}
                    style={{ zIndex: 2 }}
                    initial={{ opacity: 1 }}
                    animate={{ opacity: phase === 'sealed' || phase === 'stamp-peeling' ? 1 : 0 }}
                    transition={{ duration: 0.6, ease: 'easeInOut' }}
                    draggable={false}
                />

                {/* Open envelope back — fades in when opening */}
                <motion.img
                    src={envelopeBackSrc}
                    alt=""
                    className={layerClass}
                    style={{ zIndex: 1 }}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: phase === 'open' || phase === 'letter-unfolded' ? 1 : 0 }}
                    transition={{ duration: 0.6, ease: 'easeInOut' }}
                    draggable={false}
                />

                {/* Folded letter inside — fades in with the open envelope */}
                <motion.img
                    src={letterFoldedSrc}
                    alt=""
                    className={layerClass}
                    style={{ zIndex: 5 }}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: phase === 'open' || phase === 'letter-unfolded' ? 1 : 0 }}
                    transition={{ duration: 0.6, ease: 'easeInOut' }}
                    draggable={false}
                />

                {/* Wax seal stamp — peels up smoothly */}
                <motion.img
                    src={envelopeStampSrc}
                    alt=""
                    className={layerClass}
                    style={{
                        zIndex: 12,
                        transformOrigin: 'center bottom',
                    }}
                    initial={{ opacity: 1, rotateX: 0, y: 0 }}
                    animate={
                        phase === 'sealed' ? { opacity: 1, rotateX: 0, y: 0 } : { opacity: 0, rotateX: -60, y: -30 }
                    }
                    transition={{ duration: 1, ease: 'easeInOut' }}
                    draggable={false}
                />

                {/* Unfolded letter — rises up smoothly on top of envelope */}
                <motion.img
                    src={letterUnfoldedSrc}
                    alt=""
                    className={layerClass}
                    style={{ zIndex: 20 }}
                    initial={{ y: 20, opacity: 0 }}
                    animate={phase === 'letter-unfolded' ? { y: -40, opacity: 1 } : { y: 20, opacity: 0 }}
                    transition={{ duration: 0.8, ease: 'easeOut' }}
                    draggable={false}
                />

                {/* Text on the letter */}
                {phase === 'letter-unfolded' && (
                    <motion.div
                        className="absolute overflow-y-auto"
                        style={{
                            top: '34%',
                            left: '39%',
                            right: '37%',
                            bottom: '25%',
                            zIndex: 30,
                            scrollbarWidth: 'none',
                            // Shift up with the letter
                            transform: 'translateY(-40px)',
                        }}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ duration: 0.4, delay: 0.5 }}
                    >
                        <div className="px-3 py-2">
                            <span
                                style={{
                                    fontFamily: "'Caveat', cursive",
                                    fontSize: 16,
                                    color: '#3B2B26',
                                    lineHeight: 1.4,
                                    whiteSpace: 'pre-wrap',
                                    textAlign: 'left',
                                    display: 'block',
                                }}
                            >
                                {message}
                            </span>
                        </div>
                    </motion.div>
                )}
            </div>
        </div>
    )
}

// -- Scroll mode --
// Rolls start touching in the center, then slide apart to reveal the parchment.
// The hoggie follows the text cursor as it writes.

function ScrollMode({ message }: { message: string }): JSX.Element {
    const [unrolled, setUnrolled] = useState(false)
    const [showText, setShowText] = useState(false)
    const [hoggie, setHoggie] = useState<HoggiePos | null>(null)
    const [hoggieSettled, setHoggieSettled] = useState(false)
    const wrapperRef = useRef<HTMLDivElement>(null)

    // Once writing stops, wait for the walk animation (1.2s) then stop wiggling
    useEffect(() => {
        if (hoggie && !hoggie.isWriting) {
            const timer = setTimeout(() => setHoggieSettled(true), 1300)
            return () => clearTimeout(timer)
        }
        setHoggieSettled(false)
    }, [hoggie?.isWriting, hoggie])

    useEffect(() => {
        const t1 = setTimeout(() => setUnrolled(true), 400)
        const t2 = setTimeout(() => setShowText(true), 1200)
        return () => {
            clearTimeout(t1)
            clearTimeout(t2)
        }
    }, [])

    return (
        <div className="relative w-full h-full flex items-center justify-center overflow-hidden">
            {/* Wrapper that expands from 0 to full width — rolls are pinned to its edges
                so they naturally push apart as it grows. No left/right animation needed. */}
            <motion.div
                ref={wrapperRef}
                className="scroll-parchment-wrapper relative z-10 overflow-visible"
                style={{ height: '65%' }}
                initial={{ width: '0%' }}
                animate={{ width: unrolled ? '82%' : '0%' }}
                transition={{ duration: 0.8, ease: 'easeInOut' }}
            >
                {/* Parchment background */}
                <img
                    src={scrollParchmentSrc}
                    alt=""
                    className="absolute inset-0 w-full h-full"
                    style={{ objectFit: 'fill' }}
                    draggable={false}
                />

                {/* Left scroll roll — pinned to left edge of wrapper */}
                <img
                    src={scrollRollLeftSrc}
                    alt=""
                    className="absolute z-20"
                    style={{
                        height: '120%',
                        top: '-10%',
                        left: 0,
                        transform: 'translateX(-40%)',
                        objectFit: 'contain',
                    }}
                    draggable={false}
                />

                {/* Right scroll roll — pinned to right edge of wrapper */}
                <img
                    src={scrollRollRightSrc}
                    alt=""
                    className="absolute z-20"
                    style={{
                        height: '120%',
                        top: '-10%',
                        right: 0,
                        transform: 'translateX(40%)',
                        objectFit: 'contain',
                    }}
                    draggable={false}
                />

                {/* Scrollable text area */}
                {showText && (
                    <div
                        className="absolute overflow-y-auto z-10"
                        style={{
                            top: '16%',
                            left: '14%',
                            right: '14%',
                            bottom: '16%',
                            scrollbarWidth: 'none',
                        }}
                    >
                        <HandwrittenText text={message} onHoggieUpdate={setHoggie} />
                    </div>
                )}

                {/* Hoggie — follows cursor while writing, walks to bottom-right when done */}
                {showText &&
                    hoggie &&
                    (() => {
                        // Compute resting position as left/top so motion can smoothly
                        // interpolate from the cursor position to the corner
                        const w = wrapperRef.current
                        const restLeft = w ? w.offsetWidth - 160 + 20 : 0
                        const restTop = w ? w.offsetHeight - 160 + 40 : 0

                        return (
                            <motion.img
                                src={hoggieQuillSrc}
                                alt="Hoggie writing"
                                className="absolute z-30 pointer-events-none"
                                style={{ width: 160 }}
                                animate={{
                                    left: hoggie.isWriting ? hoggie.x + 4 : restLeft,
                                    top: hoggie.isWriting ? hoggie.y - 135 : restTop,
                                    rotate: hoggieSettled ? 0 : [-1.5, 1.5, -1.5],
                                }}
                                transition={{
                                    left: { duration: hoggie.isWriting ? 0.15 : 1.2, ease: 'easeInOut' },
                                    top: { duration: hoggie.isWriting ? 0.15 : 1.2, ease: 'easeInOut' },
                                    rotate: hoggieSettled
                                        ? { duration: 0.2 }
                                        : { duration: 0.3, repeat: Infinity, ease: 'easeInOut' },
                                }}
                                draggable={false}
                            />
                        )
                    })()}
            </motion.div>
        </div>
    )
}

// -- Galactic mode --
// Uses canvas Starfield background and a Star Wars-style crawl font.

function GalacticMode({ message }: { message: string }): JSX.Element {
    return (
        <div className="relative w-full h-full overflow-hidden">
            {/* Animated starfield canvas */}
            <Starfield speed={0.5} quantity={300} />

            {/* Crawl text */}
            <div
                className="absolute inset-0 flex items-end justify-center"
                style={{ perspective: 300, perspectiveOrigin: '50% 0%' }}
            >
                <motion.div
                    className="w-4/5 text-center"
                    style={{
                        transformStyle: 'preserve-3d',
                        rotateX: 25,
                    }}
                    initial={{ y: '120%' }}
                    animate={{ y: '-200%' }}
                    transition={{ duration: 20, ease: 'linear' }}
                >
                    <p
                        className="leading-relaxed"
                        style={{
                            fontFamily:
                                "'Trade Gothic Bold No. 2', 'Trade Gothic', 'Franklin Gothic Medium', 'Arial Narrow', Arial, sans-serif",
                            fontWeight: 700,
                            fontSize: 26,
                            letterSpacing: '0.05em',
                            color: '#FFD700',
                            textShadow: '0 0 15px rgba(255,215,0,0.4), 0 0 30px rgba(255,215,0,0.2)',
                            whiteSpace: 'pre-wrap',
                        }}
                    >
                        {message}
                    </p>
                </motion.div>
            </div>
        </div>
    )
}

// -- Captions overlay for CSM mode --
// Shows ~6 words at a time, advancing every 1.5 seconds like real closed captions.

function CaptionsOverlay({ message }: { message: string }): JSX.Element {
    const words = message.split(/\s+/)
    const chunkSize = 12
    const [chunkIndex, setChunkIndex] = useState(0)
    const totalChunks = Math.ceil(words.length / chunkSize)

    useEffect(() => {
        setChunkIndex(0)
    }, [message])

    useEffect(() => {
        if (chunkIndex >= totalChunks - 1) {
            return
        }
        const timer = setTimeout(() => setChunkIndex((i) => i + 1), 1500)
        return () => clearTimeout(timer)
    }, [chunkIndex, totalChunks])

    const currentWords = words.slice(chunkIndex * chunkSize, (chunkIndex + 1) * chunkSize).join(' ')

    return (
        <motion.div
            className="absolute bottom-14 left-0 right-0 z-20 flex justify-center px-8"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2 }}
        >
            <div
                className="w-full max-w-2xl px-6 py-3 rounded text-center"
                style={{
                    backgroundColor: 'rgba(0, 0, 0, 0.55)',
                }}
            >
                <AnimatePresence mode="wait">
                    <motion.p
                        key={chunkIndex}
                        className="text-sm leading-relaxed text-center"
                        style={{
                            color: '#fff',
                            fontFamily: 'system-ui, -apple-system, sans-serif',
                        }}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.15 }}
                    >
                        {currentWords}
                    </motion.p>
                </AnimatePresence>
            </div>
        </motion.div>
    )
}

// -- CSM mode --
// DVD screensaver with bouncing CSM image and audio playback (TODO).
// Captions toggle shows the letter text as closed captions.

// DVD color tinting — the image has a transparent background and grayscale art.
// We use sepia + saturate + hue-rotate to tint the art to each color.
// No invert needed since there's no white background to deal with.
const DVD_HUE_MAP: Record<string, number> = {
    '#1d4aff': 200,
    '#f54e00': 350,
    '#35c759': 90,
    '#f9bd2b': 15,
    '#b62ad9': 260,
    '#ff6b6b': 325,
}

const DVD_COLORS = ['#1d4aff', '#f54e00', '#35c759', '#f9bd2b', '#b62ad9', '#ff6b6b']

function CsmMode({ message }: { message: string }): JSX.Element {
    const [captionsOn, setCaptionsOn] = useState(false)
    const [color, setColor] = useState(DVD_COLORS[0])

    const { containerRef, elementRef } = useDvdScreensaver<HTMLDivElement>({
        speed: 3,
        impactCallback: (count) => setColor(DVD_COLORS[count % DVD_COLORS.length]),
    })

    return (
        <div ref={containerRef} className="relative w-full h-full overflow-hidden" style={{ backgroundColor: '#000' }}>
            {/* Bouncing DVD element */}
            <div
                ref={elementRef}
                className="absolute"
                style={{
                    top: 0,
                    left: 0,
                }}
            >
                <img
                    src={christopheDvdSrc}
                    alt="CSM"
                    style={{
                        width: 220,
                        height: 'auto',
                        filter: `sepia(1) saturate(3) hue-rotate(${DVD_HUE_MAP[color] ?? 0}deg)`,
                        transition: 'filter 0.3s ease',
                    }}
                    draggable={false}
                />
            </div>

            {/* TODO: Add audio playback of CSM reading the letter */}
            {/* When audio is added:
                - Add play/pause button
                - Sync captions with audio timestamps
                - Auto-show captions when audio plays
            */}

            {/* CC button */}
            <button
                onClick={() => setCaptionsOn(!captionsOn)}
                className="absolute bottom-4 right-4 z-30 px-3 py-1.5 rounded text-xs font-bold border-2 transition-colors"
                style={{
                    backgroundColor: captionsOn ? '#fff' : 'transparent',
                    color: captionsOn ? '#000' : '#fff',
                    borderColor: '#fff',
                }}
            >
                CC
            </button>

            {/* Captions overlay — reveals word-by-word like real CC */}
            {captionsOn && <CaptionsOverlay message={message} />}
        </div>
    )
}

// -- Main modal --

export function ConciergeModal({ isOpen, onClose, notificationId, title, body }: ConciergeModalProps): JSX.Element {
    const payload = parsePayload(body)
    const message = payload.body || title || ''
    const mode = modeForStyle(payload.notification_style)
    const wizardCommand = wizardCommandFor(notificationId)

    return (
        <>
            {/* Load Caveat font for envelope + scroll modes */}
            <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Caveat:wght@400;700&display=swap" />

            {/* Make close button visible on dark mode backgrounds (CSM/Galactic) */}
            {(mode === 'csm' || mode === 'galactic') && (
                <style>{`.LemonModal__close .LemonButton { color: #fff !important; }`}</style>
            )}

            <LemonModal isOpen={isOpen} onClose={onClose} simple closable>
                <div
                    className="flex flex-col"
                    style={{ width: '85vw', maxWidth: 960, height: '80vh', maxHeight: 720 }}
                    onClick={(e) => e.stopPropagation()}
                >
                    {/* Art area */}
                    <div className="flex-1 relative overflow-hidden">
                        <AnimatePresence mode="wait">
                            <motion.div
                                key={mode}
                                className="w-full h-full"
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                exit={{ opacity: 0 }}
                                transition={{ duration: 0.3 }}
                            >
                                {mode === 'envelope' && <EnvelopeMode message={message} />}
                                {mode === 'scroll' && <ScrollMode message={message} />}
                                {mode === 'galactic' && <GalacticMode message={message} />}
                                {mode === 'csm' && <CsmMode message={message} />}
                            </motion.div>
                        </AnimatePresence>
                    </div>

                    {/* CTA: copyable wizard command */}
                    <div className="p-3 border-t border-border">
                        <CodeSnippet language={Language.Bash} thing="command" compact>
                            {wizardCommand}
                        </CodeSnippet>
                    </div>
                </div>
            </LemonModal>
        </>
    )
}
