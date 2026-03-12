import './SimplifiedProductSelection.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconArrowRight, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand/Logomark'
import {
    BuilderHog1,
    DetectiveHog,
    ExperimentsHog,
    ExplorerHog,
    FeatureFlagHog,
    FilmCameraHog,
    GraphsHog,
    MailHog,
    MicrophoneHog,
    RobotHog,
    SurprisedHog,
} from 'lib/components/hedgehogs'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { availableOnboardingProducts, getProductIcon, toSentenceCase } from '../utils'
import { productSelectionLogic } from './productSelectionLogic'

type AvailableOnboardingProductKey = keyof typeof availableOnboardingProducts

const PRODUCT_HEDGEHOG: Partial<Record<string, React.ComponentType<{ className?: string }>>> = {
    [ProductKey.PRODUCT_ANALYTICS]: GraphsHog,
    [ProductKey.WEB_ANALYTICS]: ExplorerHog,
    [ProductKey.SESSION_REPLAY]: FilmCameraHog,
    [ProductKey.LLM_ANALYTICS]: RobotHog,
    [ProductKey.DATA_WAREHOUSE]: BuilderHog1,
    [ProductKey.FEATURE_FLAGS]: FeatureFlagHog,
    [ProductKey.EXPERIMENTS]: ExperimentsHog,
    [ProductKey.ERROR_TRACKING]: DetectiveHog,
    [ProductKey.SURVEYS]: MicrophoneHog,
    [ProductKey.WORKFLOWS]: MailHog,
}

function getSocialProof(productKey: string): string | undefined {
    const payload = getFeatureFlagPayload('onboarding-social-proof-info') as Record<string, string> | undefined
    return (
        payload?.[productKey] ??
        availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]?.socialProof
    )
}

// ─── Physics ────────────────────────────────────────────────────────────────
const ITEM_SPACING = 110
const COAST_FRICTION = 0.97
const SNAP_VEL = 0.08
const SPRING_K = 0.1
const SPRING_C = 0.55
const MAX_SPRING_VEL = 0.2
const DRAG_DEAD_ZONE = 5

// ─── Nauseous easter egg ────────────────────────────────────────────────────
const NAUSEOUS_THRESHOLD = 25
const AGITATION_DECAY = 0.98
const DIRECTION_CHANGE_BOOST = 12

// ─── Carousel hook ──────────────────────────────────────────────────────────
function useCarousel(
    itemCount: number,
    onSettle: (index: number) => void,
    initialIndex: number = 0
): {
    position: number
    isDragging: boolean
    isNauseous: boolean
    isAnimating: boolean
    activeIndex: number
    hadDragMovement: React.MutableRefObject<boolean>
    handlePointerDown: (e: React.PointerEvent) => void
    stepTo: (direction: number) => void
    goToIndex: (index: number) => void
} {
    const [position, setPosition] = useState(initialIndex)
    const [isDragging, setIsDragging] = useState(false)
    const [isNauseous, setIsNauseous] = useState(false)
    const [isAnimating, setIsAnimating] = useState(false)

    const posRef = useRef(initialIndex)
    const velRef = useRef(0)
    const targetRef = useRef<number | null>(null)
    const draggingRef = useRef(false)
    const rafRef = useRef(0)
    const settledRef = useRef<number | null>(initialIndex)
    const animatingRef = useRef(false)
    const agitationRef = useRef(0)
    const lastVelSignRef = useRef(0)
    const hadDragMovement = useRef(false)
    const onSettleRef = useRef(onSettle)
    onSettleRef.current = onSettle

    const wrapIndex = useCallback(
        (pos: number): number => ((Math.round(pos) % itemCount) + itemCount) % itemCount,
        [itemCount]
    )

    const activeIndex = wrapIndex(posRef.current)

    const updateAgitation = useCallback(() => {
        const vel = velRef.current
        const absVel = Math.abs(vel)
        const sign = vel > 0 ? 1 : vel < 0 ? -1 : 0

        if (sign !== 0 && sign !== lastVelSignRef.current && lastVelSignRef.current !== 0) {
            agitationRef.current += DIRECTION_CHANGE_BOOST * Math.min(absVel, 3)
        }
        if (sign !== 0) {
            lastVelSignRef.current = sign
        }

        if (absVel > 0.5) {
            agitationRef.current += absVel * 0.6
        }

        agitationRef.current *= AGITATION_DECAY

        setIsNauseous((prev) =>
            prev ? agitationRef.current > NAUSEOUS_THRESHOLD * 0.5 : agitationRef.current > NAUSEOUS_THRESHOLD
        )
    }, [])

    const markSettled = useCallback((idx: number) => {
        if (settledRef.current !== idx) {
            settledRef.current = idx
            onSettleRef.current(idx)
        }
        if (animatingRef.current) {
            animatingRef.current = false
            setIsAnimating(false)
        }
    }, [])

    const tick = useCallback(() => {
        updateAgitation()

        if (draggingRef.current) {
            setPosition(posRef.current)
            rafRef.current = requestAnimationFrame(tick)
            return
        }

        if (targetRef.current !== null) {
            const diff = targetRef.current - posRef.current
            velRef.current += SPRING_K * diff - SPRING_C * velRef.current

            if (Math.abs(velRef.current) > MAX_SPRING_VEL) {
                velRef.current = Math.sign(velRef.current) * MAX_SPRING_VEL
            }

            posRef.current += velRef.current

            if (Math.abs(diff) < 0.005 && Math.abs(velRef.current) < 0.005) {
                posRef.current = targetRef.current
                velRef.current = 0
                const idx = wrapIndex(targetRef.current)
                targetRef.current = null
                markSettled(idx)
            }
        } else {
            velRef.current *= COAST_FRICTION
            posRef.current += velRef.current

            if (Math.abs(velRef.current) < SNAP_VEL) {
                targetRef.current = Math.round(posRef.current)
            }
        }

        setPosition(posRef.current)

        const needsFrame =
            velRef.current !== 0 || targetRef.current !== null || agitationRef.current > NAUSEOUS_THRESHOLD * 0.3
        if (needsFrame) {
            rafRef.current = requestAnimationFrame(tick)
        }
    }, [updateAgitation, wrapIndex, markSettled])

    const startLoop = useCallback(() => {
        cancelAnimationFrame(rafRef.current)
        if (!animatingRef.current) {
            animatingRef.current = true
            setIsAnimating(true)
        }
        rafRef.current = requestAnimationFrame(tick)
    }, [tick])

    const handlePointerDown = useCallback(
        (e: React.PointerEvent) => {
            e.preventDefault()
            draggingRef.current = true
            hadDragMovement.current = false
            setIsDragging(true)

            const startX = e.clientX
            let lastX = e.clientX
            let lastTime = performance.now()
            velRef.current = 0
            targetRef.current = null
            settledRef.current = null

            const samples: number[] = []

            const onMove = (ev: PointerEvent): void => {
                const dx = ev.clientX - lastX
                const dt = Math.max(1, performance.now() - lastTime)

                if (!hadDragMovement.current && Math.abs(ev.clientX - startX) > DRAG_DEAD_ZONE) {
                    hadDragMovement.current = true
                }

                const delta = -dx / ITEM_SPACING
                posRef.current += delta

                const instantVel = delta / (dt / 16)
                samples.push(instantVel)
                if (samples.length > 5) {
                    samples.shift()
                }
                velRef.current = samples.reduce((a, b) => a + b, 0) / samples.length

                lastX = ev.clientX
                lastTime = performance.now()
                setPosition(posRef.current)
            }

            const onUp = (): void => {
                draggingRef.current = false
                setIsDragging(false)
                window.removeEventListener('pointermove', onMove)
                window.removeEventListener('pointerup', onUp)

                if (!hadDragMovement.current) {
                    // No drag movement — let onClick handle navigation
                    return
                }

                if (Math.abs(velRef.current) < 0.3) {
                    velRef.current = 0
                    targetRef.current = Math.round(posRef.current)
                }

                startLoop()
            }

            window.addEventListener('pointermove', onMove)
            window.addEventListener('pointerup', onUp)
            startLoop()
        },
        [startLoop]
    )

    const stepTo = useCallback(
        (direction: number) => {
            velRef.current = 0
            targetRef.current = Math.round(posRef.current) + direction
            settledRef.current = null
            startLoop()
        },
        [startLoop]
    )

    const goToIndex = useCallback(
        (index: number) => {
            const currentWrapped = ((posRef.current % itemCount) + itemCount) % itemCount
            let diff = index - currentWrapped
            const half = itemCount / 2
            if (diff >= half) {
                diff -= itemCount
            }
            if (diff < -half) {
                diff += itemCount
            }
            velRef.current = 0
            targetRef.current = posRef.current + diff
            settledRef.current = null
            startLoop()
        },
        [itemCount, startLoop]
    )

    useEffect(() => () => cancelAnimationFrame(rafRef.current), [])

    return {
        position,
        isDragging,
        isNauseous,
        isAnimating,
        activeIndex,
        hadDragMovement,
        handlePointerDown,
        stepTo,
        goToIndex,
    }
}

// ─── Component ──────────────────────────────────────────────────────────────

export function SimplifiedProductSelection(): JSX.Element {
    const { firstProductOnboarding, hasBrowsingHistory } = useValues(productSelectionLogic)
    const { setFirstProductOnboarding, selectSingleProduct } = useActions(productSelectionLogic)
    const { showInviteModal } = useActions(inviteLogic)

    const allProducts = Object.keys(availableOnboardingProducts) as AvailableOnboardingProductKey[]

    const initialIndex = firstProductOnboarding
        ? Math.max(0, allProducts.indexOf(firstProductOnboarding as AvailableOnboardingProductKey))
        : 0

    const [mounted, setMounted] = useState(false)
    const [settledIndex, setSettledIndex] = useState(initialIndex)
    const navigationSourceRef = useRef<'arrow_key' | 'chevron_button' | 'carousel_click' | 'drag_fling'>('arrow_key')
    const hasTrackedSpinRef = useRef(false)

    useEffect(() => {
        const timer = setTimeout(() => setMounted(true), 100)
        return () => clearTimeout(timer)
    }, [])

    const handleSettle = useCallback(
        (index: number) => {
            const prevIndex = settledIndex
            setSettledIndex(index)
            setFirstProductOnboarding(allProducts[index])

            // Track product navigation (only when the product actually changed)
            if (index !== prevIndex) {
                window.posthog?.capture('onboarding_product_browsed', {
                    product: allProducts[index],
                    previous_product: allProducts[prevIndex],
                    navigation_method: navigationSourceRef.current,
                })
            }
        },
        [allProducts, setFirstProductOnboarding, settledIndex]
    )

    const { position, isDragging, isNauseous, activeIndex, hadDragMovement, handlePointerDown, stepTo, goToIndex } =
        useCarousel(allProducts.length, handleSettle, initialIndex)

    // Track when the user triggers the nauseous hedgehog (spin for fun)
    useEffect(() => {
        if (isNauseous && !hasTrackedSpinRef.current) {
            hasTrackedSpinRef.current = true
            window.posthog?.capture('onboarding_wheel_spun_for_fun')
        }
        if (!isNauseous) {
            hasTrackedSpinRef.current = false
        }
    }, [isNauseous])

    const spotlightKey = allProducts[settledIndex]
    const spotlightProduct = availableOnboardingProducts[spotlightKey]
    const spotlightDescription = spotlightProduct.userCentricDescription || spotlightProduct.description
    const spotlightSocialProof = getSocialProof(spotlightKey)
    const HedgehogComponent = PRODUCT_HEDGEHOG[spotlightKey]

    const handleGetStarted = (): void => {
        selectSingleProduct(allProducts[activeIndex])
    }
    const handleGetStartedRef = useRef(handleGetStarted)
    handleGetStartedRef.current = handleGetStarted

    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'ArrowLeft') {
                e.preventDefault()
                navigationSourceRef.current = 'arrow_key'
                stepTo(-1)
            } else if (e.key === 'ArrowRight') {
                e.preventDefault()
                navigationSourceRef.current = 'arrow_key'
                stepTo(1)
            } else if (e.key === 'Enter') {
                e.preventDefault()
                handleGetStartedRef.current()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [stepTo])

    const getWrappedOffset = (itemIndex: number): number => {
        const wrappedPos = ((position % allProducts.length) + allProducts.length) % allProducts.length
        let offset = itemIndex - wrappedPos
        const half = allProducts.length / 2
        // Use strict inequality on one side so items at exactly ±half
        // stay put instead of jumping between sides during animation
        if (offset >= half) {
            offset -= allProducts.length
        }
        if (offset < -half) {
            offset += allProducts.length
        }
        return offset
    }

    return (
        <div className="SimplifiedProductSelection flex flex-col flex-1 w-full min-h-full p-4 items-center justify-center bg-primary overflow-x-hidden">
            {/* Subtle product color wash across the whole page */}
            <div
                className="absolute inset-0 transition-colors duration-700 pointer-events-none"
                style={{
                    backgroundColor: isNauseous ? 'rgba(34, 197, 94, 0.04)' : spotlightProduct.iconColor,
                    opacity: 0.04,
                }}
            />

            <div className="relative flex flex-col items-center justify-center flex-grow w-full max-w-2xl">
                <div className="flex justify-center mb-4">
                    <Logomark />
                </div>
                <h1 className="text-4xl font-bold text-center mb-1">What should we build first?</h1>
                <p className="text-center text-muted mb-8">
                    {hasBrowsingHistory
                        ? "We've got a hunch about where to start."
                        : "Pick your starting point — you'll unlock the rest soon enough."}
                </p>

                {/* ── Hero spotlight ── */}
                <div className="flex items-center gap-3 w-full max-w-2xl mb-6">
                    <button
                        onClick={() => {
                            navigationSourceRef.current = 'chevron_button'
                            stepTo(-1)
                        }}
                        className="shrink-0 p-2 rounded-full hover:bg-surface-primary text-muted hover:text-default transition-colors cursor-pointer"
                        aria-label="Previous product"
                    >
                        <IconChevronLeft className="text-2xl" />
                    </button>

                    <div className="flex-1 max-w-xl mx-auto rounded-xl border overflow-hidden bg-surface-primary shadow-sm">
                        {/* Color accent bar */}
                        <div
                            className="h-1.5 transition-all duration-500"
                            style={{
                                backgroundColor: isNauseous ? 'rgb(34, 197, 94)' : spotlightProduct.iconColor,
                            }}
                        />

                        <div className="h-[280px]">
                            {isNauseous ? (
                                /* ── Nauseous easter egg ── */
                                <div className="flex flex-col items-center justify-center h-full gap-4 p-6">
                                    <div className="SimplifiedProductSelection__buzz">
                                        <SurprisedHog className="w-[140px] h-[140px]" />
                                    </div>
                                    <div className="text-center">
                                        <p className="text-base font-semibold mb-1">Slow down!</p>
                                        <p className="text-muted text-sm italic">I'm getting very nauseous...</p>
                                    </div>
                                </div>
                            ) : (
                                /* ── Product spotlight ── */
                                <div className="flex h-full">
                                    {/* Hedgehog hero area — this is the star of the show */}
                                    <div className="w-[180px] shrink-0 relative overflow-hidden flex items-end justify-center">
                                        <div
                                            className="absolute inset-0 opacity-[0.12] transition-colors duration-500"
                                            style={{ backgroundColor: spotlightProduct.iconColor }}
                                        />
                                        {HedgehogComponent && (
                                            <HedgehogComponent className="relative z-10 w-[150px] h-[150px] object-contain mb-2" />
                                        )}
                                    </div>

                                    {/* Product info */}
                                    <div className="flex-1 flex flex-col justify-between p-5">
                                        <div>
                                            <div className="flex items-center gap-1.5 text-xs text-muted mb-1.5">
                                                {getProductIcon(spotlightProduct.icon, {
                                                    iconColor: spotlightProduct.iconColor,
                                                    className: 'text-sm',
                                                })}
                                                <span>{toSentenceCase(spotlightProduct.name)}</span>
                                            </div>
                                            <h2 className="text-xl font-bold mb-3 min-h-[3.5rem]">
                                                {spotlightDescription}
                                            </h2>
                                            {spotlightProduct.capabilities && (
                                                <ul className="list-none p-0 m-0 flex flex-col gap-1.5">
                                                    {spotlightProduct.capabilities.map((cap) => (
                                                        <li
                                                            key={cap}
                                                            className="text-sm text-muted flex items-center gap-2"
                                                        >
                                                            <span
                                                                className="w-1.5 h-1.5 rounded-full shrink-0"
                                                                style={{
                                                                    backgroundColor: spotlightProduct.iconColor,
                                                                }}
                                                            />
                                                            {cap}
                                                        </li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>

                                        <div className="flex flex-col gap-2 mt-2">
                                            <LemonButton
                                                type="primary"
                                                status="alt"
                                                size="large"
                                                onClick={handleGetStarted}
                                                sideIcon={<IconArrowRight />}
                                                data-attr="onboarding-continue"
                                                fullWidth
                                            >
                                                Let's go
                                            </LemonButton>
                                            {spotlightSocialProof && (
                                                <span className="text-xs text-muted text-center">
                                                    {spotlightSocialProof}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    <button
                        onClick={() => {
                            navigationSourceRef.current = 'chevron_button'
                            stepTo(1)
                        }}
                        className="shrink-0 p-2 rounded-full hover:bg-surface-primary text-muted hover:text-default transition-colors cursor-pointer"
                        aria-label="Next product"
                    >
                        <IconChevronRight className="text-2xl" />
                    </button>
                </div>

                {/* ── Arc carousel ── */}
                <div
                    className={clsx(
                        'relative w-full h-[140px] mb-4 select-none',
                        isDragging ? 'cursor-grabbing' : 'cursor-grab'
                    )}
                    onPointerDown={(e) => {
                        navigationSourceRef.current = 'drag_fling'
                        handlePointerDown(e)
                    }}
                    style={{ touchAction: 'none' }}
                >
                    {allProducts.map((productKey, index) => {
                        const product = availableOnboardingProducts[productKey]
                        const offset = getWrappedOffset(index)
                        const absOffset = Math.abs(offset)
                        const isCenter = absOffset < 0.5
                        const isVisible = absOffset <= 5

                        const x = offset * ITEM_SPACING
                        const y = absOffset * absOffset * 2
                        const scale = Math.max(0.82, 1 - absOffset * 0.035)
                        const itemOpacity = isVisible ? Math.max(0.4, 1 - absOffset * 0.12) : 0

                        const entranceDelay = Math.round(absOffset) * 60

                        return (
                            <div
                                key={productKey}
                                onClick={() => {
                                    if (isVisible && !isCenter && !hadDragMovement.current) {
                                        navigationSourceRef.current = 'carousel_click'
                                        goToIndex(index)
                                    }
                                }}
                                className={clsx(
                                    'absolute left-1/2 flex flex-col items-center gap-1.5',
                                    isVisible ? 'cursor-pointer' : 'pointer-events-none'
                                )}
                                style={{
                                    transform: mounted
                                        ? `translateX(calc(-50% + ${x}px)) translateY(${y}px) scale(${scale})`
                                        : `translateX(-50%) translateY(30px) scale(0.8)`,
                                    opacity: mounted ? itemOpacity : 0,
                                    zIndex: 10 - Math.round(absOffset),
                                    transitionDelay: !mounted ? `${entranceDelay}ms` : '0ms',
                                    transition: mounted ? 'none' : 'all 0.5s ease-in-out',
                                }}
                                data-attr={`${productKey}-arc-item`}
                            >
                                <div
                                    className={clsx('rounded-xl p-3 transition-shadow duration-200', {
                                        'border-2 bg-surface-primary shadow-lg': isCenter,
                                        'border border-primary bg-surface-primary': !isCenter,
                                    })}
                                    style={
                                        isCenter
                                            ? {
                                                  borderColor: product.iconColor,
                                                  boxShadow: `0 4px 20px ${product.iconColor}25`,
                                              }
                                            : undefined
                                    }
                                >
                                    {getProductIcon(product.icon, {
                                        iconColor: product.iconColor,
                                        className: 'text-[28px]',
                                    })}
                                </div>
                                <span
                                    className={clsx(
                                        'text-xs whitespace-nowrap',
                                        isCenter ? 'text-default font-semibold' : 'text-muted'
                                    )}
                                >
                                    {toSentenceCase(product.name)}
                                </span>
                            </div>
                        )
                    })}
                </div>

                <div className="flex items-center gap-4 text-muted text-xs mb-3">
                    <span className="flex items-center gap-1.5">
                        <kbd className="px-1.5 py-0.5 rounded border border-primary bg-surface-primary text-[10px] font-mono">
                            &larr;
                        </kbd>
                        <kbd className="px-1.5 py-0.5 rounded border border-primary bg-surface-primary text-[10px] font-mono">
                            &rarr;
                        </kbd>
                        browse
                    </span>
                    <span className="flex items-center gap-1.5">
                        <kbd className="px-1.5 py-0.5 rounded border border-primary bg-surface-primary text-[10px] font-mono">
                            &crarr;
                        </kbd>
                        select
                    </span>
                </div>
                <p className="text-muted text-xs mb-2">You can always add more from Settings.</p>
                <p className="text-muted text-sm">
                    Need help from a team member? <Link onClick={() => showInviteModal()}>Invite them</Link>
                </p>
            </div>
        </div>
    )
}
