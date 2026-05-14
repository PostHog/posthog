import { useValues } from 'kea'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import { ConciergeModal } from 'lib/components/ConciergeModal/ConciergeModal'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'

import christopheConciergeSrc from 'public/concierge/christophe-concierge.png'

const IMG_WIDTH = 180
const PADDING = 24
const HIDDEN_FRACTION = 0.45

function PixelSpeechBubble({ text }: { text: string }): JSX.Element {
    return (
        <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.96 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            style={{
                position: 'absolute',
                bottom: '100%',
                right: 8,
                marginBottom: 14,
                maxWidth: 240,
                minWidth: 120,
                pointerEvents: 'none',
                imageRendering: 'pixelated',
            }}
        >
            {/* Bubble body — transparent background, pixel-stepped black border */}
            <div
                style={{
                    position: 'relative',
                    background: 'transparent',
                    color: '#000000',
                    fontFamily: "'Press Start 2P', 'VT323', ui-monospace, monospace",
                    fontSize: 10,
                    lineHeight: 1.6,
                    padding: '12px 14px',
                    textAlign: 'left',
                    // Single stepped black border, no inner fill ring
                    boxShadow:
                        '0 -4px 0 0 #000, 0 4px 0 0 #000, -4px 0 0 0 #000, 4px 0 0 0 #000,' +
                        ' -4px -4px 0 0 #000, 4px -4px 0 0 #000, -4px 4px 0 0 #000, 4px 4px 0 0 #000',
                    wordBreak: 'break-word',
                }}
            >
                {text}
            </div>
            {/* Stepped pixel tail pointing down-right toward the head — all black squares */}
            <div
                style={{
                    position: 'absolute',
                    right: 22,
                    top: '100%',
                    width: 0,
                    height: 0,
                }}
            >
                <div
                    style={{
                        position: 'absolute',
                        width: 16,
                        height: 4,
                        background: '#000',
                        left: -8,
                        top: 0,
                    }}
                />
                <div
                    style={{
                        position: 'absolute',
                        width: 8,
                        height: 4,
                        background: '#000',
                        left: -4,
                        top: 4,
                    }}
                />
                <div
                    style={{
                        position: 'absolute',
                        width: 4,
                        height: 4,
                        background: '#000',
                        left: -2,
                        top: 8,
                    }}
                />
            </div>
        </motion.div>
    )
}

export function FloatingConcierge(): JSX.Element | null {
    const { firstUnreadConcierge } = useValues(sidePanelNotificationsLogic)
    const [hovered, setHovered] = useState(false)
    const [modalOpen, setModalOpen] = useState(false)
    const [mounted, setMounted] = useState(false)
    const title = firstUnreadConcierge?.title ?? ''

    useEffect(() => {
        setMounted(true)
    }, [])

    const handleClick = (): void => {
        if (firstUnreadConcierge) {
            setModalOpen(true)
        }
    }

    if (!mounted || typeof document === 'undefined') {
        return null
    }

    return createPortal(
        <>
            {/* Load pixel font for speech bubble */}
            <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" />

            {/* Stepped rainbow flashing — discrete jumps between muted color hues */}
            <style>{`
                @keyframes conciergeRainbowFlash {
                    0%   { filter: sepia(0.7) saturate(1.6) brightness(0.95) hue-rotate(0deg); }
                    16%  { filter: sepia(0.7) saturate(1.6) brightness(0.95) hue-rotate(60deg); }
                    33%  { filter: sepia(0.7) saturate(1.6) brightness(0.95) hue-rotate(120deg); }
                    50%  { filter: sepia(0.7) saturate(1.6) brightness(0.95) hue-rotate(180deg); }
                    66%  { filter: sepia(0.7) saturate(1.6) brightness(0.95) hue-rotate(240deg); }
                    83%  { filter: sepia(0.7) saturate(1.6) brightness(0.95) hue-rotate(300deg); }
                    100% { filter: sepia(0.7) saturate(1.6) brightness(0.95) hue-rotate(360deg); }
                }
            `}</style>

            {firstUnreadConcierge && (
                <ConciergeModal
                    isOpen={modalOpen}
                    onClose={() => setModalOpen(false)}
                    notificationId={firstUnreadConcierge.id}
                    title={firstUnreadConcierge.title}
                    body={firstUnreadConcierge.body}
                />
            )}

            <motion.div
                initial={{ opacity: 0, y: `${HIDDEN_FRACTION * 100}%` }}
                animate={{ opacity: 1, y: modalOpen ? '0%' : `${HIDDEN_FRACTION * 100}%` }}
                whileHover={{ y: '0%' }}
                onHoverStart={() => setHovered(true)}
                onHoverEnd={() => setHovered(false)}
                onClick={handleClick}
                transition={{
                    opacity: { duration: 0.8, ease: 'easeOut' },
                    y: { type: 'spring', stiffness: 220, damping: 22 },
                }}
                style={{
                    position: 'fixed',
                    right: PADDING,
                    bottom: 0,
                    width: IMG_WIDTH,
                    // Above LemonModal (--z-modal: 1100) so the head isn't behind the backdrop blur.
                    zIndex: 1200,
                    userSelect: 'none',
                    cursor: 'pointer',
                }}
            >
                <AnimatePresence>{hovered && title && <PixelSpeechBubble key="bubble" text={title} />}</AnimatePresence>

                <motion.img
                    src={christopheConciergeSrc}
                    alt=""
                    aria-hidden
                    draggable={false}
                    animate={{
                        y: [0, -14, 0, -6, 0],
                        rotate: [0, -6, 5, -4, 3, -2, 0],
                    }}
                    transition={{
                        y: {
                            duration: 1.2,
                            times: [0, 0.25, 0.55, 0.75, 1],
                            ease: 'easeOut',
                            repeat: Infinity,
                            repeatDelay: 6,
                            delay: 0.8,
                        },
                        rotate: {
                            duration: 1.4,
                            ease: 'easeInOut',
                            repeat: Infinity,
                            repeatDelay: 9 + Math.random() * 4,
                            delay: 3 + Math.random() * 3,
                        },
                    }}
                    style={{
                        display: 'block',
                        width: '100%',
                        height: 'auto',
                        userSelect: 'none',
                        animation: 'conciergeRainbowFlash 3s steps(1, end) infinite',
                    }}
                />
            </motion.div>
        </>,
        document.body
    )
}
