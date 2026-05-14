import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'

import { IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import envelopeBackSrc from 'public/concierge/envelope/envelope-back.png'
import envelopeFlapSrc from 'public/concierge/envelope/envelope-flap.png'
import letterFoldedSrc from 'public/concierge/envelope/letter-folded.png'
import letterPanelBottomSrc from 'public/concierge/envelope/letter-panel-bottom.png'
import letterPanelMiddleSrc from 'public/concierge/envelope/letter-panel-middle.png'
import letterPanelTopSrc from 'public/concierge/envelope/letter-panel-top.png'
import hoggieQuillSrc from 'public/concierge/hoggie-quill.png'
import scrollParchmentSrc from 'public/concierge/scroll/scroll-parchment.png'
import scrollRollLeftSrc from 'public/concierge/scroll/scroll-roll-left.png'
import scrollRollRightSrc from 'public/concierge/scroll/scroll-roll-right.png'

import { Starfield } from './Starfield'

type DeliveryMode = 'envelope' | 'scroll' | 'galactic'

interface ConciergePayload {
    body?: string
    call_to_action?: string
    notification_style?: string
}

export interface ConciergeModalProps {
    isOpen: boolean
    onClose: () => void
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
    const [phase, setPhase] = useState<'closed' | 'flap-open' | 'letter-rising' | 'letter-unfolded'>('closed')

    useEffect(() => {
        const timers = [
            setTimeout(() => setPhase('flap-open'), 400),
            setTimeout(() => setPhase('letter-rising'), 1000),
            setTimeout(() => setPhase('letter-unfolded'), 1800),
        ]
        return () => timers.forEach(clearTimeout)
    }, [])

    return (
        <div className="relative w-full h-full flex items-center justify-center overflow-hidden">
            {/* Envelope back */}
            <img src={envelopeBackSrc} alt="" className="absolute w-[85%] bottom-[10%]" draggable={false} />

            {/* Letter (folded, then unfolded panels) */}
            <AnimatePresence>
                {phase === 'letter-rising' && (
                    <motion.img
                        key="letter-folded"
                        src={letterFoldedSrc}
                        alt=""
                        className="absolute w-[75%] bottom-[15%]"
                        initial={{ y: 0, opacity: 0 }}
                        animate={{ y: -60, opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.7, ease: 'easeOut' }}
                        draggable={false}
                    />
                )}
            </AnimatePresence>

            {phase === 'letter-unfolded' && (
                <div className="absolute w-[75%] top-[3%] flex flex-col items-center">
                    {/* Top panel */}
                    <motion.img
                        src={letterPanelTopSrc}
                        alt=""
                        className="w-full"
                        initial={{ rotateX: 180, originY: 1 }}
                        animate={{ rotateX: 0 }}
                        transition={{ duration: 0.5, ease: 'easeOut' }}
                        draggable={false}
                    />
                    {/* Middle panel with text */}
                    <div className="relative w-full">
                        <img src={letterPanelMiddleSrc} alt="" className="w-full" draggable={false} />
                        <div className="absolute inset-0 flex items-center justify-center p-3">
                            <span
                                className="text-center"
                                style={{
                                    fontFamily: "'Caveat', cursive",
                                    fontSize: 16,
                                    color: '#3B2B26',
                                    lineHeight: 1.3,
                                    whiteSpace: 'pre-wrap',
                                }}
                            >
                                {message}
                            </span>
                        </div>
                    </div>
                    {/* Bottom panel */}
                    <motion.img
                        src={letterPanelBottomSrc}
                        alt=""
                        className="w-full"
                        initial={{ rotateX: -180, originY: 0 }}
                        animate={{ rotateX: 0 }}
                        transition={{ duration: 0.5, ease: 'easeOut', delay: 0.2 }}
                        draggable={false}
                    />
                </div>
            )}

            {/* Envelope flap */}
            <motion.img
                src={envelopeFlapSrc}
                alt=""
                className="absolute w-[85%] bottom-[28%]"
                style={{ transformOrigin: 'top center' }}
                animate={{
                    rotateX: phase === 'closed' ? 0 : 180,
                    zIndex: phase === 'closed' ? 10 : -1,
                }}
                transition={{ duration: 0.6, ease: 'easeInOut' }}
                draggable={false}
            />
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
    }, [hoggie?.isWriting])

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

// -- Main modal --

function isDeliveryMode(value: string | undefined): value is DeliveryMode {
    return value === 'envelope' || value === 'scroll' || value === 'galactic'
}

export function ConciergeModal({ isOpen, onClose, title, body }: ConciergeModalProps): JSX.Element {
    const payload = parsePayload(body)
    const message = payload.body || title || ''
    const cta = payload.call_to_action
    const mode: DeliveryMode = isDeliveryMode(payload.notification_style) ? payload.notification_style : 'envelope'

    return (
        <>
            {/* Load Caveat font for envelope + scroll modes */}
            <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Caveat:wght@400;700&display=swap" />

            <LemonModal isOpen={isOpen} onClose={onClose} simple closable hideCloseButton>
                <div
                    className="flex flex-col"
                    style={{ width: '85vw', maxWidth: 960, height: '80vh', maxHeight: 720 }}
                    onClick={(e) => e.stopPropagation()}
                >
                    {/* Header: close button */}
                    <div className="flex items-center justify-end gap-2 p-3 border-b border-border">
                        <LemonButton icon={<IconX />} size="small" onClick={onClose} tooltip="Close" />
                    </div>

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
                            </motion.div>
                        </AnimatePresence>
                    </div>

                    {/* CTA button */}
                    <div className="p-3 border-t border-border flex justify-center">
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                // TODO(concierge): Add CTA functionality — this could navigate
                                // to a URL, open a resource, or trigger an action based on the
                                // notification payload. For now it just closes the modal.
                                onClose()
                            }}
                        >
                            {cta || 'Run this skill'}
                        </LemonButton>
                    </div>
                </div>
            </LemonModal>
        </>
    )
}

// -- Temporary test harness -- delete before merging --
const TEST_BODY = JSON.stringify({
    body: 'Dear Sarah,\n\nThis is your CSM, Christophe. I am checking back in after our call yesterday. I wanted to make sure you and your team have everything you need to get started.\n\nLorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n\nWith care,\nChristophe',
    call_to_action: 'Book a follow-up',
    notification_style: 'royal',
})

export function ConciergeModalTest(): JSX.Element {
    const [open, setOpen] = useState(true)
    return (
        <div className="p-4">
            <LemonButton type="primary" onClick={() => setOpen(true)}>
                Open concierge modal
            </LemonButton>
            <ConciergeModal
                isOpen={open}
                onClose={() => setOpen(false)}
                title="A note from your CSM"
                body={TEST_BODY}
            />
        </div>
    )
}
