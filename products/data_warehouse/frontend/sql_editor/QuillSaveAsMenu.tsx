import { IconInfo } from '@posthog/icons'
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

import type { SaveAsMenuProps } from './saveAsTargets'

export function QuillSaveAsMenuItems({ targets, onSelect }: SaveAsMenuProps): JSX.Element {
    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>Save query as</DropdownMenuLabel>
            {targets.map((target) => {
                const Icon = target.icon

                return (
                    <div key={target.id} className="flex w-full min-w-0 items-stretch">
                        <DropdownMenuItem
                            className="min-w-0 flex-1"
                            onClick={() => onSelect(target.id)}
                            disabledReason={target.disabledReason}
                            tooltip={target.helpText}
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
                        <Tooltip disableHoverablePopup={false}>
                            <TooltipTrigger
                                closeOnClick={false}
                                render={
                                    <Button
                                        variant="default"
                                        size="icon-sm"
                                        className="my-1 me-1 ms-auto shrink-0 self-start"
                                        tabIndex={-1}
                                        aria-label={`Learn more about ${target.label.toLowerCase()}`}
                                        data-attr={`sql-editor-save-as-${target.id}-help`}
                                    />
                                }
                            >
                                <IconInfo />
                            </TooltipTrigger>
                            <TooltipContent side="left" align="center" className="max-w-xs flex-col items-start">
                                <span className="text-xs">{target.helpText}</span>
                                <Button
                                    variant="link"
                                    size="inline"
                                    render={<LinkPrimitive to={target.docsUrl} target="_blank" />}
                                >
                                    Read the docs
                                </Button>
                            </TooltipContent>
                        </Tooltip>
                    </div>
                )
            })}
        </DropdownMenuGroup>
    )
}
