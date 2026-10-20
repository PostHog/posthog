import { IconCopy, IconEllipsis, IconGroupIntersect, IconPencil, IconTrash } from '@posthog/icons'
import {
    Dot,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { QuillIconButton } from 'lib/components/QuillIconButton/QuillIconButton'

import { apiValueToMathType } from 'products/product_analytics/frontend/insights/trends/mathsLogic'

import { ActionFilterRowControlsArgs } from './actionFilterRowControls'
import { QuillMathMenuItems } from './QuillMathMenuItems'
import { useMathSelectorChoices } from './useMathSelectorChoices'

type QuillActionFilterRowMenuProps = ActionFilterRowControlsArgs['menu'] & {
    index: number
    onRename: () => void
    onDuplicate: () => void
    onDelete: () => void
    /** Present only when the series can be combined into an inline group. */
    onCombine: (() => void) | null
}

/** The quill series row menu, the counterpart of `ActionFilterRowMenu`. */
export function QuillActionFilterRowMenu({
    index,
    isTrendsContext,
    isFunnelContext,
    isStepOptional,
    math,
    mathGroupTypeIndex,
    mathAvailability,
    trendsDisplayCategory,
    readOnly,
    query,
    filter,
    hideRename,
    hideDuplicate,
    hideDeleteBtn,
    singleFilter,
    onMathSelect,
    onUpdateOptional,
    onRename,
    onDuplicate,
    onDelete,
    onCombine,
}: QuillActionFilterRowMenuProps): JSX.Element {
    const mathChoices = useMathSelectorChoices({ index, mathAvailability, trendsDisplayCategory, query })
    const hasFunnelSettings = isFunnelContext && (math != null || isStepOptional(index + 1))

    return (
        <span className="relative inline-flex">
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <QuillIconButton
                            label="Show more actions"
                            icon={<IconEllipsis />}
                            data-attr={`more-button-${index}`}
                        />
                    }
                />
                <DropdownMenuContent align={isTrendsContext ? 'end' : 'start'} className="w-max min-w-48 max-w-80">
                    {isFunnelContext ? (
                        <>
                            <DropdownMenuGroup>
                                <DropdownMenuLabel>Count</DropdownMenuLabel>
                                <QuillMathMenuItems
                                    choices={mathChoices}
                                    value={apiValueToMathType(math, mathGroupTypeIndex)}
                                    onChange={(value) => onMathSelect(index, value)}
                                    disabled={readOnly}
                                />
                            </DropdownMenuGroup>
                            <DropdownMenuSeparator />
                        </>
                    ) : null}
                    {isFunnelContext && index > 0 ? (
                        <>
                            <DropdownMenuCheckboxItem
                                checked={!!filter.optionalInFunnel}
                                onCheckedChange={(checked: boolean) => onUpdateOptional(checked)}
                                closeOnClick={false}
                            >
                                Optional step
                            </DropdownMenuCheckboxItem>
                            <DropdownMenuSeparator />
                        </>
                    ) : null}
                    {onCombine ? (
                        <>
                            <DropdownMenuItem onClick={onCombine} data-attr={`show-prop-combine-${index}`}>
                                <IconGroupIntersect />
                                Combine
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                        </>
                    ) : null}
                    {!hideRename ? (
                        <DropdownMenuItem onClick={onRename} data-attr={`show-prop-rename-${index}`}>
                            <IconPencil />
                            Rename
                        </DropdownMenuItem>
                    ) : null}
                    {!singleFilter && !hideDuplicate ? (
                        <DropdownMenuItem onClick={onDuplicate} data-attr={`show-prop-duplicate-${index}`}>
                            <IconCopy />
                            Duplicate
                        </DropdownMenuItem>
                    ) : null}
                    {!singleFilter && !hideDeleteBtn ? (
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={onDelete}
                            data-attr={`delete-prop-filter-${index}`}
                        >
                            <IconTrash />
                            Delete
                        </DropdownMenuItem>
                    ) : null}
                </DropdownMenuContent>
            </DropdownMenu>
            {hasFunnelSettings ? <Dot aria-hidden className="absolute top-0 right-0" /> : null}
        </span>
    )
}
