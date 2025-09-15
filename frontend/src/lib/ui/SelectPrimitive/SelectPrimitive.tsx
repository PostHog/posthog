import * as SelectPrimitiveBase from '@radix-ui/react-select'
import * as React from 'react'

import { IconCheck, IconChevronRight } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'

import { ButtonPrimitive, ButtonPrimitiveProps } from '../Button/ButtonPrimitives'
import { Label } from '../Label/Label'

function SelectPrimitive({ ...props }: React.ComponentProps<typeof SelectPrimitiveBase.Root>): JSX.Element {
    return <SelectPrimitiveBase.Root data-slot="select" {...props} />
}

function SelectPrimitiveGroup({ ...props }: React.ComponentProps<typeof SelectPrimitiveBase.Group>): JSX.Element {
    return <SelectPrimitiveBase.Group data-slot="select-group" {...props} />
}

function SelectPrimitiveValue({ ...props }: React.ComponentProps<typeof SelectPrimitiveBase.Value>): JSX.Element {
    return <SelectPrimitiveBase.Value data-slot="select-value" {...props} />
}

function SelectPrimitiveTrigger({
    className,
    size = 'base',
    children,
    buttonProps,
    ...props
}: React.ComponentProps<typeof SelectPrimitiveBase.Trigger> & {
    size?: 'sm' | 'base'
    buttonProps?: ButtonPrimitiveProps
}): JSX.Element {
    return (
        <SelectPrimitiveBase.Trigger
            data-slot="select-trigger"
            data-size={size}
            className={className}
            asChild
            {...props}
        >
            <ButtonPrimitive {...buttonProps}>
                {children}
                <SelectPrimitiveBase.Icon asChild className="ml-auto">
                    <IconChevronRight className="ml-auto size-3 text-secondary rotate-90 group-data-[state=open]/button-primitive:rotate-270 transition-transform duration-200 prefers-reduced-motion:transition-none" />
                </SelectPrimitiveBase.Icon>
            </ButtonPrimitive>
        </SelectPrimitiveBase.Trigger>
    )
}

function SelectPrimitiveContent({
    className,
    children,
    position = 'popper',
    matchTriggerWidth,
    ...props
}: React.ComponentProps<typeof SelectPrimitiveBase.Content> & {
    matchTriggerWidth?: boolean
}): JSX.Element {
    return (
        <SelectPrimitiveBase.Portal>
            <SelectPrimitiveBase.Content
                data-slot="select-content"
                className={cn(
                    'primitive-menu-content',
                    position === 'popper' &&
                        'data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1',
                    matchTriggerWidth && 'min-w-[var(--radix-select-trigger-width)]',
                    className
                )}
                position={position}
                {...props}
            >
                <SelectPrimitiveBase.Viewport
                    className={cn(
                        position === 'popper' &&
                            'h-[var(--radix-select-trigger-height)] w-full scroll-my-1 max-h-[calc(var(--radix-select-content-available-height)-var(--radix-select-trigger-height))]'
                    )}
                    asChild
                >
                    <ScrollableShadows
                        direction="vertical"
                        styledScrollbars
                        innerClassName="primitive-menu-content-inner"
                    >
                        {children}
                    </ScrollableShadows>
                </SelectPrimitiveBase.Viewport>
            </SelectPrimitiveBase.Content>
        </SelectPrimitiveBase.Portal>
    )
}

function SelectPrimitiveLabel({
    className,
    children,
    ...props
}: React.ComponentProps<typeof SelectPrimitiveBase.Label>): JSX.Element {
    return (
        <SelectPrimitiveBase.Label
            data-slot="select-label"
            className={cn('px-2 py-1.5 text-xs pl-7', className)}
            asChild
            {...props}
        >
            <Label intent="menu">{children}</Label>
        </SelectPrimitiveBase.Label>
    )
}

export type SelectPrimitiveItemProps = React.ComponentProps<typeof SelectPrimitiveBase.Item> & {
    label?: string
    value: string
    buttonProps?: Omit<ButtonPrimitiveProps, 'disabled'>
}

function SelectPrimitiveItem({ className, children, buttonProps, ...props }: SelectPrimitiveItemProps): JSX.Element {
    return (
        <SelectPrimitiveBase.Item data-slot="select-item" className={className} asChild {...props}>
            <ButtonPrimitive menuItem disabled={props.disabled} {...buttonProps}>
                <span className="flex place-items-center size-[var(--button-height)] shrink-0">
                    <SelectPrimitiveBase.ItemIndicator>
                        <IconCheck className="size-[var(--button-height)]" />
                    </SelectPrimitiveBase.ItemIndicator>
                </span>
                <SelectPrimitiveBase.ItemText>{children}</SelectPrimitiveBase.ItemText>
            </ButtonPrimitive>
        </SelectPrimitiveBase.Item>
    )
}

function SelectPrimitiveSeparator({
    className,
    ...props
}: React.ComponentProps<typeof SelectPrimitiveBase.Separator>): JSX.Element {
    return (
        <SelectPrimitiveBase.Separator
            data-slot="select-separator"
            className={cn('-mx-1 my-1 h-px bg-border-primary', className)}
            {...props}
        />
    )
}

export {
    SelectPrimitive,
    SelectPrimitiveContent,
    SelectPrimitiveGroup,
    SelectPrimitiveItem,
    SelectPrimitiveLabel,
    SelectPrimitiveSeparator,
    SelectPrimitiveTrigger,
    SelectPrimitiveValue,
}
