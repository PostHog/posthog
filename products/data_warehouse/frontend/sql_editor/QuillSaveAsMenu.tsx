import type { FocusEvent } from 'react'

import {
    Badge,
    Button,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { SaveAsMenuProps, SaveAsTarget, SaveAsTargetId } from './saveAsTargets'

export function QuillSaveAsMenuItems({ targets, onSelect }: SaveAsMenuProps): JSX.Element {
    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>Save query as</DropdownMenuLabel>
            {targets.map((target) => (
                <QuillSaveAsMenuItem key={target.id} target={target} onSelect={onSelect} />
            ))}
        </DropdownMenuGroup>
    )
}

function QuillSaveAsMenuItem({
    target,
    onSelect,
}: {
    target: SaveAsTarget
    onSelect: (id: SaveAsTargetId) => void
}): JSX.Element {
    const Icon = target.icon
    return (
        <Tooltip disableHoverablePopup={false}>
            {/* Disabled items ignore the pointer, so a wrapper catches the hover. The item's own
                `disabledReason` would replace the help text, and the label already shows the reason. */}
            <TooltipTrigger render={<div className="w-full min-w-0" />}>
                {/* The menu takes focus back from the item as the pointer leaves it. Keep that blur away
                    from the trigger, or the tooltip closes before the pointer reaches its docs link. */}
                <div className="contents" onFocus={stopPropagation} onBlur={stopPropagation}>
                    <DropdownMenuItem
                        className="w-full min-w-0"
                        onClick={() => onSelect(target.id)}
                        disabled={!!target.disabledReason}
                        data-attr={target.dataAttr}
                        description={
                            <span className="flex flex-col gap-0.5">
                                <span>{target.description}</span>
                                {target.disabledReason ? (
                                    <span className="text-warning-foreground">{target.disabledReason}</span>
                                ) : null}
                            </span>
                        }
                    >
                        <Icon />
                        {target.label}
                        {target.recommended ? <Badge>Recommended</Badge> : null}
                    </DropdownMenuItem>
                </div>
            </TooltipTrigger>
            <TooltipContent side="left" align="center" className="max-w-xs flex-col items-start">
                <span className="text-xs">{target.helpText}</span>
                <Button variant="link" size="inline" render={<LinkPrimitive to={target.docsUrl} target="_blank" />}>
                    Read the docs
                </Button>
            </TooltipContent>
        </Tooltip>
    )
}

function stopPropagation(event: FocusEvent): void {
    event.stopPropagation()
}
