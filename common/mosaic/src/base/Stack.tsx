import type { HTMLAttributes, ReactElement } from 'react'

import { cn } from '../utils'

const gapStyles = {
    xs: 'gap-1',
    sm: 'gap-2',
    md: 'gap-3',
    lg: 'gap-4',
} as const

const alignStyles = {
    start: 'items-start',
    center: 'items-center',
    end: 'items-end',
    stretch: 'items-stretch',
    baseline: 'items-baseline',
} as const

const justifyStyles = {
    start: 'justify-start',
    center: 'justify-center',
    end: 'justify-end',
    between: 'justify-between',
} as const

export interface StackProps extends HTMLAttributes<HTMLDivElement> {
    direction?: 'row' | 'column'
    gap?: keyof typeof gapStyles
    align?: keyof typeof alignStyles
    justify?: keyof typeof justifyStyles
    wrap?: boolean
}

export function Stack({
    direction = 'column',
    gap = 'md',
    align,
    justify,
    wrap = false,
    className,
    ...props
}: StackProps): ReactElement {
    return (
        <div
            className={cn(
                'flex',
                direction === 'row' ? 'flex-row' : 'flex-col',
                gapStyles[gap],
                align && alignStyles[align],
                justify && justifyStyles[justify],
                wrap && 'flex-wrap',
                className
            )}
            {...props}
        />
    )
}
