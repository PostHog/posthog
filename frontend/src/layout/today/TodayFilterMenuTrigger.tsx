import { IconFilter } from '@posthog/icons'
import { Button, Dot, DropdownMenuTrigger, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

/** The funnel button that opens a list's filter menu. A dot says a filter narrows the list. */
export function TodayFilterMenuTrigger({ active, dataAttr }: { active: boolean; dataAttr: string }): JSX.Element {
    const label = active ? 'Filters on' : 'Filter'
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon-xs"
                                aria-label={label}
                                className={cn(
                                    'relative text-muted-foreground',
                                    active && 'bg-fill-selected text-foreground'
                                )}
                                data-attr={dataAttr}
                            />
                        }
                    />
                }
            >
                <IconFilter />
                {active && <Dot aria-hidden className="absolute top-0 right-0" />}
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}
