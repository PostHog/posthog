import { useLayoutEffect, useMemo } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { timeToX } from '../lib/chartTime'
import { BetIdeaNumber } from './BetIdeaNumber'

export interface BetIdeaPin {
    number: number
    at: string
    label: string
    highlighted: boolean
}

export const PIN_ROW = 22
export const PIN_LEVEL = 20

export function pinRowHeight(levels: number): number {
    return levels ? PIN_ROW + PIN_LEVEL * (levels - 1) : 0
}

export function BetIdeaPins({
    pins,
    onLevels,
}: {
    pins: BetIdeaPin[]
    onLevels: (levels: number) => void
}): JSX.Element {
    const { scales, dimensions, labels } = useChartLayout()
    const placed = useMemo(() => {
        const ends: number[] = []
        return pins
            .map((pin) => ({ ...pin, x: timeToX(pin.at, labels, scales.x) }))
            .filter((pin): pin is BetIdeaPin & { x: number } => pin.x !== null)
            .map((pin) => ({ ...pin, x: Math.min(dimensions.width - 9, Math.max(9, pin.x)) }))
            .sort((a, b) => a.x - b.x)
            .map((pin) => {
                const free = ends.findIndex((end) => pin.x - end >= 22)
                const level = free < 0 ? ends.length : free
                ends[level] = pin.x
                return { ...pin, level }
            })
    }, [pins, labels, scales.x, dimensions.width])
    const levels = placed.reduce((most, pin) => Math.max(most, pin.level + 1), 0)
    useLayoutEffect(() => {
        onLevels(levels)
    }, [levels, onLevels])
    const plotBottom = dimensions.plotTop + dimensions.plotHeight
    return (
        <>
            {placed.map((pin) => {
                const top = pin.level * PIN_LEVEL
                return (
                    <div key={`${pin.number}:${pin.at}`} data-attr="bets-idea-pin" title={pin.label}>
                        <svg
                            className="BetIdeaPins__line absolute overflow-visible"
                            style={{ left: pin.x, top: top + 18, height: Math.max(0, plotBottom - top - 18) }}
                            aria-hidden
                        >
                            <line x1={0} x2={0} y1={1} y2={Math.max(0, plotBottom - top - 19)} />
                        </svg>
                        <BetIdeaNumber
                            number={pin.number}
                            won={pin.highlighted}
                            className="BetIdeaPins__badge absolute"
                            style={{ left: pin.x, top }}
                        />
                    </div>
                )
            })}
        </>
    )
}
