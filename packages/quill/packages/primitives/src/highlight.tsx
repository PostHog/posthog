import './highlight.css'

import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

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
        animate: {
            true: 'quill-highlight--animate',
            false: '',
        },
    },
    defaultVariants: {
        color: 'orange',
        animate: false,
    },
})

type HighlightColor = NonNullable<VariantProps<typeof highlightVariants>['color']>

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
    style,
    render,
    ...props
}: HighlightProps): React.ReactElement {
    const elementRef = React.useRef<HTMLElement>(null)
    // `done` swaps back to the static styles, so the text-clipped glyphs of the stroke don't outlive it.
    const [phase, setPhase] = React.useState<'waiting' | 'drawing' | 'done'>(animate ? 'waiting' : 'done')
    const [autoDuration, setAutoDuration] = React.useState(MIN_DURATION_MS)

    React.useEffect(() => {
        if (!animate) {
            setPhase('done')
            return
        }
        const element = elementRef.current
        if (!element) {
            return
        }
        setPhase('waiting')
        setAutoDuration(strokeDuration(element.textContent ?? ''))
        if (typeof IntersectionObserver === 'undefined') {
            setPhase('drawing')
            return
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    setPhase('drawing')
                    observer.disconnect()
                }
            },
            { rootMargin: '0px 0px -10% 0px' }
        )
        observer.observe(element)
        return () => observer.disconnect()
    }, [animate])

    return useRender({
        defaultTagName: 'mark',
        ref: elementRef,
        props: mergeProps<'mark'>(
            {
                'data-quill': '',
                className: cn(highlightVariants({ color, animate: phase !== 'done' }), className),
                style: {
                    '--quill-highlight-duration': `${duration ?? autoDuration}ms`,
                    '--quill-highlight-delay': `${delay}ms`,
                } as React.CSSProperties,
                onTransitionEnd: (event: React.TransitionEvent<HTMLElement>) => {
                    if (event.target === event.currentTarget && event.propertyName === 'background-size') {
                        setPhase('done')
                    }
                },
            } as Omit<React.ComponentProps<'mark'>, 'ref'>,
            { style, ...props }
        ),
        render,
        state: {
            slot: 'highlight',
            color,
            drawn: phase === 'drawing',
        },
    })
}

export { Highlight, highlightVariants }
export type { HighlightColor, HighlightProps }
