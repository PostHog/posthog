import { Fragment, useRef, useState } from 'react'

import { IconEllipsis, IconPencil, IconStack } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Popover,
    PopoverContent,
    cn,
} from '@posthog/quill'

import { BreakdownTaxonomicFilter, type MetricHeaderActionsProps } from './metricHeaderActions'

export function QuillMetricHeaderActions({
    experiment,
    sections,
    canAddBreakdown,
    onBreakdownChange,
    onEdit,
}: MetricHeaderActionsProps): JSX.Element {
    const [menuOpen, setMenuOpen] = useState(false)
    const [breakdownOpen, setBreakdownOpen] = useState(false)
    const anchorRef = useRef<HTMLDivElement>(null)

    return (
        <div
            ref={anchorRef}
            className={cn(
                'flex flex-shrink-0 gap-1 transition-opacity',
                menuOpen || breakdownOpen
                    ? 'opacity-100'
                    : 'opacity-0 group-hover/metric-cell:opacity-100 focus-within:opacity-100 pointer-coarse:opacity-100'
            )}
        >
            <Button size="icon-xs" aria-label="Edit metric" tooltip="Edit metric" onClick={onEdit}>
                <IconPencil />
            </Button>
            <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
                <DropdownMenuTrigger
                    render={<Button size="icon-xs" aria-label="More actions" tooltip="More actions" />}
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    {sections.map((section, index) => (
                        <Fragment key={section.key}>
                            {index > 0 && <DropdownMenuSeparator />}
                            <DropdownMenuGroup>
                                {section.key === 'edit' && canAddBreakdown && (
                                    <DropdownMenuItem onClick={() => setBreakdownOpen(true)}>
                                        <IconStack />
                                        Add breakdown
                                    </DropdownMenuItem>
                                )}
                                {section.items.map((action) => (
                                    <DropdownMenuItem
                                        key={action.key}
                                        variant={action.danger ? 'destructive' : 'default'}
                                        disabledReason={action.disabledReason}
                                        data-attr={action.dataAttr}
                                        onClick={action.onSelect}
                                    >
                                        {action.icon}
                                        {action.label}
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuGroup>
                        </Fragment>
                    ))}
                </DropdownMenuContent>
            </DropdownMenu>
            <Popover open={breakdownOpen} onOpenChange={setBreakdownOpen}>
                <PopoverContent anchor={anchorRef} side="left" align="start" className="w-auto p-0">
                    <BreakdownTaxonomicFilter
                        experiment={experiment}
                        onChange={(breakdown) => {
                            onBreakdownChange(breakdown)
                            setBreakdownOpen(false)
                        }}
                    />
                </PopoverContent>
            </Popover>
        </div>
    )
}
