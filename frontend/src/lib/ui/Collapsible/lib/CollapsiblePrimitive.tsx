import { Collapsible } from '@base-ui/react/collapsible'
import { cloneElement, isValidElement } from 'react'

import { cn } from 'lib/utils/css-classes'

export type CollapsiblePrimitiveProps = React.ComponentProps<typeof Collapsible.Root>
export function CollapsiblePrimitive(props: CollapsiblePrimitiveProps): JSX.Element {
    return <Collapsible.Root {...props} />
}

export type CollapsiblePrimitiveContentProps = React.ComponentProps<typeof Collapsible.Panel>
export function CollapsiblePrimitiveContent({ className, ...props }: CollapsiblePrimitiveContentProps): JSX.Element {
    return (
        <Collapsible.Panel
            className={cn(
                'h-[var(--collapsible-panel-height)] overflow-hidden transition-[height] duration-200 ease-out data-[starting-style]:h-0 data-[ending-style]:h-0',
                className
            )}
            {...props}
        />
    )
}

export type CollapsiblePrimitiveTriggerProps = React.ComponentProps<typeof Collapsible.Trigger>
export function CollapsiblePrimitiveTrigger({
    disabled,
    render,
    ...props
}: CollapsiblePrimitiveTriggerProps): JSX.Element {
    // base-ui's Collapsible.Trigger sets focusableWhenDisabled, so it only emits aria-disabled
    // and strips the native `disabled` attribute. Inject `disabled` into the rendered element
    // so Tailwind's :disabled selectors (e.g. disabled:cursor-not-allowed) apply.
    const renderWithDisabled = isValidElement(render)
        ? cloneElement(render as React.ReactElement<{ disabled?: boolean }>, { disabled })
        : (render ?? <button type="button" disabled={disabled} />)
    return <Collapsible.Trigger disabled={disabled} render={renderWithDisabled} {...props} />
}
