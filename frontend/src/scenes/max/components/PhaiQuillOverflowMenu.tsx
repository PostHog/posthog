import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

export function PhaiQuillOverflowMenu({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <DropdownMenu>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <DropdownMenuTrigger
                            render={<Button size="icon" aria-label="More options" data-attr="run-staff-menu" />}
                        />
                    }
                >
                    <IconEllipsis />
                </TooltipTrigger>
                <TooltipContent side="bottom">More options</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="w-56">
                {children}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
