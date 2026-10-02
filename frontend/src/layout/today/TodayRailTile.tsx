import { cn } from '@posthog/quill'

export interface TodayRailTileProps {
    label: string
    icon: JSX.Element
    active: boolean
    onClick: () => void
    dataAttr: string
}

export function TodayRailTile({ label, icon, active, onClick, dataAttr }: TodayRailTileProps): JSX.Element {
    return (
        <button
            type="button"
            aria-label={label}
            aria-current={active ? 'page' : undefined}
            data-attr={dataAttr}
            onClick={onClick}
            className={cn(
                'group flex w-full shrink-0 cursor-pointer flex-col items-center gap-1 outline-none hover:text-foreground',
                active ? 'text-foreground' : 'text-muted-foreground'
            )}
        >
            <span
                className={cn(
                    'flex size-10 items-center justify-center rounded-md [&_svg]:size-5',
                    'group-focus-visible:ring-2 group-focus-visible:ring-[var(--ring)]',
                    active ? 'bg-[var(--fill-selected)]' : 'group-hover:bg-[var(--fill-hover)]'
                )}
            >
                {icon}
            </span>
            <span className="max-w-full truncate px-0.5 text-[10px] leading-3 font-medium">{label}</span>
        </button>
    )
}
