import type { IconProps } from '@phosphor-icons/react'
import type { ComponentType } from 'react'

import { cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface TodayRailTileProps {
    label: string
    Icon: ComponentType<IconProps>
    active: boolean
    to: string | undefined
    onClick: () => void
    dataAttr: string
}

export function TodayRailTile({ label, Icon, active, to, onClick, dataAttr }: TodayRailTileProps): JSX.Element {
    return (
        <LinkPrimitive
            to={to}
            aria-label={label}
            aria-current={active ? 'page' : undefined}
            data-attr={dataAttr}
            onClick={(event) => {
                // Cmd/ctrl and middle clicks never reach here, so the browser still opens those in a new tab.
                event.preventDefault()
                onClick()
            }}
            className={cn(
                'group flex w-full shrink-0 cursor-pointer flex-col items-center gap-1 outline-none hover:text-foreground',
                active ? 'text-foreground' : 'text-muted-foreground'
            )}
        >
            <span
                className={cn(
                    'flex size-10 items-center justify-center rounded-md',
                    'group-focus-visible:ring-2 group-focus-visible:ring-[var(--ring)]',
                    active ? 'bg-[var(--fill-selected)]' : 'group-hover:bg-[var(--fill-hover)]'
                )}
            >
                <Icon size={20} weight={active ? 'fill' : 'regular'} />
            </span>
            <span className="max-w-full truncate px-0.5 text-[10px] leading-3 font-medium">{label}</span>
        </LinkPrimitive>
    )
}
