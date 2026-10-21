import React, { useCallback, useState } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import chartHog from './hogs/chart.png'
import coffeeRunHog from './hogs/coffee-run.png'
import drManhattanHog from './hogs/dr-manhattan.png'
import experimentHog from './hogs/experiment.png'
import explorerHog from './hogs/explorer.png'
import heartHog from './hogs/heart.png'
import mailboxHog from './hogs/mailbox.png'
import noirHog from './hogs/noir.png'
import partyHog from './hogs/party.png'
import reporterHog from './hogs/reporter.png'
import rocketHog from './hogs/rocket.png'
import shockedHog from './hogs/shocked.png'
import starHog from './hogs/star.png'
import successHog from './hogs/success.png'
import surveyHog from './hogs/survey.png'

// Confetti hogs are vendored from @posthog/brand, downscaled to 64x64 so this animation stays self-contained and lightweight.
const images: string[] = [
    shockedHog,
    successHog,
    explorerHog,
    coffeeRunHog,
    rocketHog,
    drManhattanHog,
    heartHog,
    starHog,
    chartHog,
    noirHog,
    mailboxHog,
    surveyHog,
    experimentHog,
    partyHog,
    reporterHog,
]

interface Particle {
    x: number
    y: number
    vx: number
    vy: number
    size: number
    imageIndex: number
    opacity: number
}

interface HogfettiOptions {
    count?: number
    power?: number
    duration?: number
    maxSize?: number
}

interface HogfettiHook {
    trigger: () => void
    HogfettiComponent: React.FC
}

export const useHogfetti = (options: HogfettiOptions = {}): HogfettiHook => {
    const [particleSets, setParticleSets] = useState<Particle[][]>([])
    const [dimensions, setDimensions] = useState({ width: window.innerWidth, height: window.innerHeight })

    useOnMountEffect(() => {
        const handleResize = (): void => {
            setDimensions({ width: window.innerWidth, height: window.innerHeight })
        }

        window.addEventListener('resize', handleResize)
        return () => window.removeEventListener('resize', handleResize)
    })

    const { count = 50, power = 5, duration = 2000, maxSize = 60 } = options

    const createParticle = (centerX: number, centerY: number): Particle => {
        const angle = Math.random() * Math.PI * 2
        const velocity = Math.random() * power + 2
        return {
            x: centerX,
            y: centerY,
            vx: Math.cos(angle) * velocity,
            vy: Math.sin(angle) * velocity,
            size: Math.random() * (maxSize - 20) + 20,
            imageIndex: Math.floor(Math.random() * images.length),
            opacity: 1,
        }
    }

    const trigger = useCallback((): void => {
        const centerX = Math.random() * dimensions.width
        const centerY = Math.random() * dimensions.height * 0.5

        const newParticles = Array.from({ length: count }, () => createParticle(centerX, centerY))
        setParticleSets((prev) => [...prev, newParticles])

        const startTime = Date.now()
        const animationFrame = (): void => {
            const elapsed = Date.now() - startTime
            if (elapsed < duration) {
                setParticleSets((prevSets) =>
                    prevSets.map((set) =>
                        set.map((particle) => ({
                            ...particle,
                            x: particle.x + particle.vx,
                            y: particle.y + particle.vy,
                            vy: particle.vy + 0.1, // Gravity effect
                            vx: particle.vx * 0.99, // Air resistance
                            opacity: 1 - elapsed / duration,
                        }))
                    )
                )
                requestAnimationFrame(animationFrame)
            } else {
                setParticleSets((prev) => prev.slice(1))
            }
        }
        requestAnimationFrame(animationFrame)
    }, [count, power, duration, maxSize, dimensions]) // oxlint-disable-line react-hooks/exhaustive-deps

    const HogfettiComponent: React.FC = () =>
        particleSets.length === 0 ? null : (
            // eslint-disable-next-line react/forbid-dom-props
            <div className="Hogfetti fixed top-0 left-0 w-full h-full pointer-events-none" style={{ zIndex: 9999 }}>
                {particleSets.flatMap((set, setIndex) =>
                    set.map((particle, particleIndex) => {
                        const hogSrc = images[particle.imageIndex]
                        return (
                            <div
                                key={`${setIndex}-${particleIndex}`}
                                className="absolute"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    left: `${particle.x}px`,
                                    top: `${particle.y}px`,
                                    opacity: particle.opacity,
                                    transition: 'opacity 0.1s linear',
                                }}
                            >
                                <img src={hogSrc} width={particle.size} height={particle.size} alt="" />
                            </div>
                        )
                    })
                )}
            </div>
        )

    return { trigger, HogfettiComponent }
}
