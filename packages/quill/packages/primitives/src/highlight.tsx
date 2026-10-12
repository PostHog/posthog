import './highlight.css'

import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { useReducedMotion } from './lib/use-reduced-motion'
import { cn } from './lib/utils'

const highlightVariants = cva('quill-highlight', {
    variants: {
        color: {
            orange: 'quill-highlight--color-orange',
            red: 'quill-highlight--color-red',
            yellow: 'quill-highlight--color-yellow',
            green: 'quill-highlight--color-green',
            blue: 'quill-highlight--color-blue',
            purple: 'quill-highlight--color-purple',
        },
    },
    defaultVariants: {
        color: 'orange',
    },
})

type HighlightColor = NonNullable<VariantProps<typeof highlightVariants>['color']>

// `done` is the static highlight, so the text-clipped glyphs of the stroke never outlive it.
type Stroke = { phase: 'waiting' } | { phase: 'drawing'; durationMs: number } | { phase: 'done' }

const WAITING: Stroke = { phase: 'waiting' }
const DONE: Stroke = { phase: 'done' }

const MS_PER_CHARACTER = 30
const MIN_DURATION_MS = 350
const MAX_DURATION_MS = 1600

// A marker moves at a steady hand speed, so a long phrase takes longer to cover than a short one.
function strokeDuration(text: string): number {
    return Math.min(MAX_DURATION_MS, Math.max(MIN_DURATION_MS, text.length * MS_PER_CHARACTER))
}

interface HighlightProps extends Omit<useRender.ComponentProps<'mark'>, 'color'> {
    color?: HighlightColor
    /** Draw the highlight like a marker stroke the first time it scrolls into view. */
    animate?: boolean
    /** Stroke length in ms. Defaults to a value based on the text length. */
    duration?: number
    /** Wait this many ms after the text enters the view before the stroke starts. */
    delay?: number
}

function Highlight({
    className,
    color = 'orange',
    animate = false,
    duration,
    delay = 0,
    render,
    ...props
}: HighlightProps): React.ReactElement {
    const elementRef = React.useRef<HTMLElement>(null)
    const reducedMotion = useReducedMotion()
    const strokes = animate && !reducedMotion
    const [strokeState, setStroke] = React.useState<Stroke>(WAITING)
    const stroke = strokes ? strokeState : DONE

    React.useEffect(() => {
        const element = elementRef.current
        if (!strokes || !element) {
            return
        }
        // Re-arm when `animate` turns back on after an earlier stroke.
        setStroke(WAITING)
        const draw = (): void => setStroke({ phase: 'drawing', durationMs: strokeDuration(element.textContent ?? '') })
        if (typeof IntersectionObserver === 'undefined') {
            draw()
            return
        }
        const observer = new IntersectionObserver((entries) => {
            if (entries.some((entry) => entry.isIntersecting)) {
                observer.disconnect()
                draw()
            }
        })
        observer.observe(element)
        return () => observer.disconnect()
    }, [strokes])

    return useRender({
        defaultTagName: 'mark',
        ref: elementRef,
        props: mergeProps<'mark'>(
            {
                'data-quill': '',
                className: cn(highlightVariants({ color }), className),
                style:
                    stroke.phase === 'drawing'
                        ? ({
                              '--quill-highlight-duration': `${duration ?? stroke.durationMs}ms`,
                              '--quill-highlight-delay': `${delay}ms`,
                          } as React.CSSProperties)
                        : undefined,
                onTransitionEnd: (event: React.TransitionEvent<HTMLElement>) => {
                    if (event.target === event.currentTarget && event.propertyName === 'background-size') {
                        setStroke(DONE)
                    }
                },
            } as Omit<React.ComponentProps<'mark'>, 'ref'>,
            props
        ),
        render,
        state: {
            slot: 'highlight',
            color,
            phase: stroke.phase,
        },
    })
}

export { Highlight, highlightVariants }
export type { HighlightColor, HighlightProps }
