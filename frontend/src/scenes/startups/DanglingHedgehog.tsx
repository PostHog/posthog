import './DanglingHedgehog.scss'

import * as climber2Png from '@posthog/brand/hoggies/png/climber-2'

import { pngHoggie } from 'lib/brand/hoggies'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

const HedgehogClimber = pngHoggie(climber2Png)

/**
 * Pixels of rope held above the column. The rope's end sits at the very top of the
 * illustration, so without this overshoot it would come into view as the hedgehog descends.
 * It also puts the point the rope swings around off screen, where an anchor would be.
 */
const ROPE_OVERSHOOT = 120

/** Share of the column height above the hedgehog's feet when it hangs at rest. */
const HOG_REST_POSITION = '62%'

/**
 * A hedgehog that climbs a rope down the side of the page. Sticks to the top of the scrolling
 * page, so the page keeps its own scrollbar at the edge of the window.
 *
 * The illustration is a square canvas: a bare, near-vertical rope fills the top half and the
 * hedgehog hangs from it in the bottom half. Each half renders as its own crop of the image, so
 * the rope can take the full height of the column without the hedgehog losing its proportions.
 * The rope crop holds an image box twice its own height, which stretches the rope alone, and a
 * straight line looks the same when it is stretched vertically.
 */
export function DanglingHedgehog({ className }: { className?: string }): JSX.Element {
    // The visual-regression runner pins every animation to its last keyframe, and Storybook has
    // no reason to animate at all, so both render the hedgehog at rest.
    const animated = !inStorybook() && !inStorybookTestRunner()

    return (
        <div
            className={cn(
                'DanglingHedgehog sticky top-0 self-start w-75 shrink-0 overflow-hidden pointer-events-none',
                className
            )}
            aria-hidden
        >
            <div
                className={cn('absolute inset-x-0', animated && 'DanglingHedgehog__rig')}
                style={{ top: `-${ROPE_OVERSHOOT}px`, height: `calc(${HOG_REST_POSITION} + ${ROPE_OVERSHOOT}px)` }}
            >
                {/* Rope and hedgehog turn together around the top of the rope, the way a climber on a
                    fixed line does, so the rope stays straight through the hand that holds it. */}
                <div
                    className={cn(
                        'DanglingHedgehog__pendulum flex flex-col justify-end h-full',
                        animated && 'is-swinging'
                    )}
                >
                    <div className="relative w-full flex-1 overflow-hidden">
                        <HedgehogClimber
                            className="absolute top-0 left-0 w-full"
                            style={{ height: '200%', aspectRatio: 'auto', objectFit: 'fill' }}
                            loading="eager"
                        />
                    </div>
                    <div className="DanglingHedgehog__hog relative w-full aspect-[2/1]">
                        <HedgehogClimber className="absolute bottom-0 left-0 w-full" loading="eager" />
                    </div>
                </div>
            </div>
        </div>
    )
}
