import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import * as React from 'react'

import './icon-stack.css'
import { cn } from './lib/utils'

const IconStack = React.forwardRef<HTMLSpanElement, React.ComponentProps<'span'>>(function IconStack(
    { className, children, style, ...props },
    ref
) {
    const items = React.Children.toArray(children)
    return (
        <span
            ref={ref}
            data-quill
            data-slot="icon-stack"
            className={cn('quill-icon-stack', className)}
            style={
                {
                    ...style,
                    '--icon-stack-count': items.length,
                } as React.CSSProperties
            }
            {...props}
        >
            {items.map((child, index) => (
                <span
                    key={React.isValidElement(child) ? child.key : index}
                    className="quill-icon-stack__slot"
                    style={{ '--icon-stack-index': index } as React.CSSProperties}
                >
                    {child}
                </span>
            ))}
        </span>
    )
})

const IconStackItem = React.forwardRef<
    HTMLSpanElement,
    useRender.ComponentProps<'span'> & { color?: string; active?: boolean }
>(function IconStackItem({ className, color, active = false, style, render, ...props }, ref) {
    return useRender({
        ref,
        defaultTagName: 'span',
        props: mergeProps<'span'>(
            {
                'aria-hidden': render ? undefined : true,
                className: cn('quill-icon-stack__item', className),
                style: color
                    ? ({
                          ...style,
                          '--icon-stack-color': color,
                      } as React.CSSProperties)
                    : style,
            },
            props
        ),
        render,
        state: {
            slot: 'icon-stack-item',
            active,
            colored: !!color,
        },
    })
})

export { IconStack, IconStackItem }
