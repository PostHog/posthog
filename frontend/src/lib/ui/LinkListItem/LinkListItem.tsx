import { IconEllipsis } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'

function Root({ children }: { children: React.ReactNode }): JSX.Element {
    return <DropdownMenu>{children}</DropdownMenu>
}

function Group({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element {
    return (
        <ButtonGroupPrimitive fullWidth className={cn('group', className)}>
            {children}
        </ButtonGroupPrimitive>
    )
}

function Trigger({ className }: { className?: string } = {}): JSX.Element {
    return (
        <DropdownMenuTrigger asChild>
            <ButtonPrimitive
                iconOnly
                className={cn(
                    'group absolute right-0',
                    'translate-x-full opacity-0',
                    'group-hover:translate-x-0 group-hover:opacity-100 group-focus-within:translate-x-0 group-focus-within:opacity-100',
                    'data-[state=open]:translate-x-0 data-[state=open]:opacity-100 focus-visible:translate-x-0 focus-visible:opacity-100',
                    'transition-[opacity] duration-100 ease-initial -outline-offset-2',
                    className
                )}
            >
                <IconEllipsis className="text-tertiary size-3 group-hover:text-primary z-10" />
            </ButtonPrimitive>
        </DropdownMenuTrigger>
    )
}

function Actions({
    children,
    align = 'end',
    className,
}: {
    children: React.ReactNode
    align?: 'start' | 'end'
    className?: string
}): JSX.Element {
    return (
        <DropdownMenuContent align={align} loop className={cn('max-w-[250px]', className)}>
            {children}
        </DropdownMenuContent>
    )
}

function Content({
    icon,
    title,
    meta,
    isLoading,
}: {
    icon?: React.ReactNode
    title: string
    meta?: React.ReactNode
    isLoading?: boolean
}): JSX.Element {
    return (
        <>
            {icon && (
                <span className="size-4 text-secondary opacity-50 group-hover:opacity-100 transition-all duration-50">
                    {icon}
                </span>
            )}
            <span className="flex-1 line-clamp-1 text-primary">{title}</span>
            {isLoading && <Spinner className="h-3 w-3" />}
            {meta && (
                <span
                    className={cn(
                        'opacity-30 text-xs pr-1.5 transition-opacity duration-100',
                        'group-hover:opacity-0 group-has-[[data-state=open]]:opacity-0 group-has-focus-within:opacity-0'
                    )}
                >
                    {meta}
                </span>
            )}
        </>
    )
}

export const LinkListItem = {
    Root,
    Group,
    Trigger,
    Actions,
    Content,
}
