import { useEffect, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardGroup,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { SaveAsChooserProps } from './saveAsTargets'
import type { SaveAsTargetId } from './saveAsTargets'

export function QuillSaveAsDialog({ isOpen, targets, onClose, onSelect }: SaveAsChooserProps): JSX.Element {
    const [openHelpTarget, setOpenHelpTarget] = useState<SaveAsTargetId | null>(null)

    useEffect(() => {
        if (!isOpen) {
            setOpenHelpTarget(null)
        }
    }, [isOpen])

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent size="wide" data-attr="sql-editor-save-as-dialog">
                <DialogHeader>
                    <DialogTitle>Save query as</DialogTitle>
                    <DialogDescription>Choose what you want to create from this query.</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <CardGroup>
                        {targets.map((target) => {
                            const Icon = target.icon
                            const isDisabled = !!target.disabledReason

                            return (
                                <Card
                                    key={target.id}
                                    size="sm"
                                    className={cn('p-0', isDisabled && 'bg-fill-secondary')}
                                >
                                    <div className="flex min-w-0">
                                        <button
                                            type="button"
                                            aria-disabled={isDisabled}
                                            onClick={() => !isDisabled && onSelect(target.id)}
                                            data-attr={target.dataAttr}
                                            className={cn(
                                                'flex min-w-0 flex-1 items-start gap-3 px-3 py-3 text-start',
                                                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30',
                                                isDisabled ? 'cursor-not-allowed' : 'cursor-pointer hover:bg-fill-hover'
                                            )}
                                        >
                                            <Icon className="mt-0.5 shrink-0" />
                                            <span className="flex min-w-0 flex-1 flex-col gap-1">
                                                <span className="flex flex-wrap items-center gap-2">
                                                    <Text size="sm" weight="medium" render={<span />}>
                                                        {target.label}
                                                    </Text>
                                                    {target.recommended ? <Badge>Recommended</Badge> : null}
                                                </span>
                                                <Text size="xs" variant="muted" render={<span />}>
                                                    {target.description}
                                                </Text>
                                                {target.disabledReason ? (
                                                    <Text
                                                        size="xs"
                                                        render={<span />}
                                                        className="text-warning-foreground"
                                                    >
                                                        {target.disabledReason}
                                                    </Text>
                                                ) : null}
                                            </span>
                                        </button>
                                        <Tooltip
                                            open={openHelpTarget === target.id}
                                            onOpenChange={(open) => setOpenHelpTarget(open ? target.id : null)}
                                            disableHoverablePopup={false}
                                        >
                                            <TooltipTrigger
                                                closeOnClick={false}
                                                render={
                                                    <Button
                                                        variant="default"
                                                        size="icon-sm"
                                                        className="m-2 shrink-0"
                                                        aria-label={`About ${target.label.toLowerCase()}`}
                                                        data-attr={`sql-editor-save-as-${target.id}-help`}
                                                        onClick={() => setOpenHelpTarget(target.id)}
                                                    />
                                                }
                                            >
                                                <IconInfo />
                                            </TooltipTrigger>
                                            <TooltipContent
                                                side="left"
                                                align="center"
                                                className="max-w-xs flex-col items-start"
                                            >
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
                                </Card>
                            )
                        })}
                    </CardGroup>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
