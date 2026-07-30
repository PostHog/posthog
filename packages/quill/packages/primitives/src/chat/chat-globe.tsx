import * as React from 'react'

import { cn } from '../lib/utils'
import { useReducedMotion } from '../lib/use-reduced-motion'

/**
 * A globe whose meridians sweep, reading as "browsing the web". Vendored from the aicss web-search
 * pattern. Where {@link ../spinner#Spinner} says only that something is loading, this says what — so
 * use it for fetching a page or a source, and the Spinner for everything else.
 *
 * Sizes and tints itself from its container like any other icon (see the Icons section of
 * AGENTS.md), so drop it in bare.
 */

// Four meridian shapes, left-most to right-most. Tweening between them in order sweeps a line across
// the face; six copies at staggered offsets read as one rotating globe.
const MERIDIANS = {
    left: 'M6.057 11.565 C2.081 11.565 0.371 8.159 0.371 5.964 C0.371 3.642 2.152 0.329 6.05 0.329',
    midLeft: 'M6.012 11.55 C4.575 10.496 3.333 8.116 3.321 5.964 C3.307 3.399 4.974 0.977 6.012 0.329',
    midRight: 'M6.012 11.55 C7.211 10.781 8.715 8.287 8.715 5.964 C8.715 3.399 7.24 1.233 6.012 0.329',
    right: 'M6.012 11.55 C9.677 11.55 11.65 8.487 11.65 5.964 C11.65 3.499 9.748 0.329 6.012 0.329',
} as const

const SWEEP = [MERIDIANS.left, MERIDIANS.midLeft, MERIDIANS.midRight, MERIDIANS.right, MERIDIANS.left].join(';')

/*
 * The paths are drawn to fill a 12-unit box edge to edge, but lucide keeps its art at 20 of 24 units
 * — 91.7% of the box once the stroke is counted — and pads the rest. Sized to the same 0.875rem as
 * its neighbours, an unpadded globe therefore renders ~14% wider than the circles beside it.
 *
 * So pad the viewBox instead of touching the geometry: widen the box until the globe's outer edge
 * lands on lucide's 91.7%, and scale the stroke with it so the line keeps the weight it renders at
 * today. Solving both together for r=5.7: box 13.48, stroke 0.95.
 */
const VIEW_BOX_SIZE = 13.48
// Rounded, or binary float leaves `-0.7400000000000002` sitting in the markup.
const VIEW_BOX_PAD = Math.round(((VIEW_BOX_SIZE - 12) / 2) * 100) / 100
const VIEW_BOX = `${-VIEW_BOX_PAD} ${-VIEW_BOX_PAD} ${VIEW_BOX_SIZE} ${VIEW_BOX_SIZE}`
const STROKE_WIDTH = 0.95

const DURATION = '7.2s'
// One full sweep split six ways, so a meridian crosses the face at an even cadence.
const STARTS = ['0s', '-1.2s', '-2.4s', '-3.6s', '-4.8s', '-6s']
const EASE_IN_OUT = '0.42 0 0.58 1'

function ChatGlobe({ className, ...props }: React.ComponentProps<'svg'>): React.ReactElement {
    const reducedMotion = useReducedMotion()

    return (
        <svg
            data-quill
            data-slot="globe"
            viewBox={VIEW_BOX}
            // Fallback only: containers size their bare icons in CSS, which beats these attributes.
            width="14"
            height="14"
            fill="none"
            stroke="currentColor"
            strokeWidth={STROKE_WIDTH}
            strokeLinecap="round"
            aria-hidden="true"
            className={cn('quill-chat-globe', className)}
            {...props}
        >
            <circle cx="6" cy="6" r="5.7" opacity="0.9" />
            <line x1="0.3" y1="6" x2="11.7" y2="6" opacity="0.9" />
            {reducedMotion ? (
                // Still globe: two fixed meridians read as a sphere without anything moving. SMIL
                // ignores `prefers-reduced-motion`, so the only way to honour it is to not render it.
                <>
                    <path d={MERIDIANS.midLeft} opacity="0.9" />
                    <path d={MERIDIANS.midRight} opacity="0.9" />
                </>
            ) : (
                STARTS.map((begin) => (
                    <path key={begin} d={MERIDIANS.left} opacity="0">
                        <animate
                            attributeName="d"
                            dur={DURATION}
                            begin={begin}
                            repeatCount="indefinite"
                            calcMode="spline"
                            keyTimes="0;0.25;0.5;0.75;1"
                            keySplines={[EASE_IN_OUT, EASE_IN_OUT, EASE_IN_OUT, EASE_IN_OUT].join(';')}
                            values={SWEEP}
                        />
                        {/* Fade in at the left limb and out at the right, so meridians don't pop. */}
                        <animate
                            attributeName="opacity"
                            dur={DURATION}
                            begin={begin}
                            repeatCount="indefinite"
                            calcMode="linear"
                            keyTimes="0;0.05;0.7;0.75;1"
                            values="0;0.9;0.9;0;0"
                        />
                    </path>
                ))
            )}
        </svg>
    )
}

export { ChatGlobe }
