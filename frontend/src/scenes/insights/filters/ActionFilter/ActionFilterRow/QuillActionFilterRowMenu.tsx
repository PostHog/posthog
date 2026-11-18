import { IconCopy, IconEllipsis, IconGroupIntersect, IconPencil, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { QuillMathSubMenu } from './QuillMathSubMenu'
import type { MathSelectorProps } from './types'

export interface QuillActionFilterRowMenuProps {
    index: number
    isTrendsContext: boolean
    isFunnelContext: boolean
    isStepOptional: (step: number) => boolean
    mathSelectorProps: MathSelectorProps
    optionalInFunnel?: boolean
    onUpdateOptional: (checked: boolean) => void
    onCombine?: () => void
    onRename?: () => void
    onDuplicate?: () => void
    onDelete?: () => void
}

export function QuillActionFilterRowMenu({
    index,
    isTrendsContext,
    isFunnelContext,
    isStepOptional,
    mathSelectorProps,
    optionalInFunnel,
    onUpdateOptional,
    onCombine,
    onRename,
    onDuplicate,
    onDelete,
}: QuillActionFilterRowMenuProps): JSX.Element {
    const hasStepSettings = isFunnelContext && (mathSelectorProps.math != null || isStepOptional(index + 1))
    const label = hasStepSettings ? 'Show more actions (this step has custom settings)' : 'Show more actions'
    const showOptionalStep = isFunnelContext && index > 0
    const hasStepGroup = isFunnelContext || showOptionalStep
    const hasEditGroup = !!onCombine || !!onRename || !!onDuplicate

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon"
                        aria-label={label}
                        tooltip={label}
                        indicator={hasStepSettings ? 'default' : undefined}
                        data-attr={`more-button-${index}`}
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align={isTrendsContext ? 'end' : 'start'}>
                {isFunnelContext && <QuillMathSubMenu {...mathSelectorProps} />}
                {showOptionalStep && (
                    <DropdownMenuCheckboxItem
                        checked={!!optionalInFunnel}
                        onCheckedChange={(checked) => onUpdateOptional(checked)}
                        tooltip="Optional steps show conversion rates from the last mandatory step, but are not necessary to move to the next step in the funnel"
                    >
                        Optional step
                    </DropdownMenuCheckboxItem>
                )}
                {hasStepGroup && hasEditGroup && <DropdownMenuSeparator />}
                {onCombine && (
                    <DropdownMenuItem
                        onClick={onCombine}
                        tooltip="Count multiple events as a single event"
                        data-attr={`show-prop-combine-${index}`}
                    >
                        <IconGroupIntersect />
                        Combine
                    </DropdownMenuItem>
                )}
                {onRename && (
                    <DropdownMenuItem onClick={onRename} data-attr={`show-prop-rename-${index}`}>
                        <IconPencil />
                        Rename
                    </DropdownMenuItem>
                )}
                {onDuplicate && (
                    <DropdownMenuItem onClick={onDuplicate} data-attr={`show-prop-duplicate-${index}`}>
                        <IconCopy />
                        Duplicate
                    </DropdownMenuItem>
                )}
                {onDelete && (
                    <>
                        {(hasStepGroup || hasEditGroup) && <DropdownMenuSeparator />}
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={onDelete}
                            data-attr={`delete-prop-filter-${index}`}
                        >
                            <IconTrash />
                            Delete
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
