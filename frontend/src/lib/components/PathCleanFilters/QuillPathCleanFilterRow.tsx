import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'
import { Badge, Button, TableCell, TableRow, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { SortableDragIcon } from 'lib/lemon-ui/icons'
import { isValidRegexp } from 'lib/utils/regexp'

import { PathCleaningFilter } from '~/types'

import { parseAliasToReadable } from './PathCleanFilterItem'
import { PathRegexModal } from './PathRegexModal'

export function QuillPathCleanFilterRow({
    filter,
    index,
    onEdit,
    onRemove,
    disabledReason,
}: {
    filter: PathCleaningFilter
    index: number
    onEdit: (filter: PathCleaningFilter) => void
    onRemove: () => void
    disabledReason: string | null
}): JSX.Element {
    const [isModalVisible, setIsModalVisible] = useState(false)
    const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
        id: `filter-${index}`,
    })

    const regex = filter.regex ?? ''
    const isInvalidRegex = !isValidRegexp(regex)

    return (
        <>
            {isModalVisible && (
                <PathRegexModal
                    filter={filter}
                    isOpen={isModalVisible}
                    onClose={() => setIsModalVisible(false)}
                    onSave={(updatedFilter: PathCleaningFilter) => {
                        onEdit(updatedFilter)
                        setIsModalVisible(false)
                    }}
                />
            )}
            <TableRow
                ref={disabledReason ? null : setNodeRef}
                className={isDragging ? 'relative z-10 bg-background shadow-md' : undefined}
                style={{
                    transform: CSS.Transform.toString(transform),
                    transition: isDragging ? 'none' : transition,
                }}
            >
                <TableCell>
                    <span
                        className="flex cursor-grab items-center justify-center text-muted-foreground active:cursor-grabbing"
                        {...attributes}
                        {...listeners}
                    >
                        <SortableDragIcon className="size-3" />
                    </span>
                </TableCell>
                <TableCell className="text-muted-foreground">{index + 1}</TableCell>
                <TableCell>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Badge
                                    variant={isInvalidRegex ? 'destructive' : 'default'}
                                    className="max-w-full font-mono"
                                />
                            }
                        >
                            <span className="truncate" translate="no">
                                {regex || '(Empty)'}
                            </span>
                        </TooltipTrigger>
                        <TooltipContent>{isInvalidRegex ? 'Invalid regex pattern' : regex}</TooltipContent>
                    </Tooltip>
                </TableCell>
                <TableCell>
                    <Tooltip>
                        <TooltipTrigger render={<span className="block truncate font-mono" translate="no" />}>
                            {parseAliasToReadable(filter.alias || '(Empty)')}
                        </TooltipTrigger>
                        <TooltipContent>{filter.alias}</TooltipContent>
                    </Tooltip>
                </TableCell>
                <TableCell>
                    <div className="flex items-center gap-1">
                        <Button
                            size="icon-sm"
                            aria-label="Edit rule"
                            tooltip="Edit rule"
                            onClick={() => setIsModalVisible(true)}
                            disabledReason={disabledReason}
                        >
                            <IconPencil />
                        </Button>
                        <Button
                            size="icon-sm"
                            variant="destructive-outline"
                            aria-label="Delete rule"
                            tooltip="Delete rule"
                            onClick={onRemove}
                            disabledReason={disabledReason}
                        >
                            <IconTrash />
                        </Button>
                    </div>
                </TableCell>
            </TableRow>
        </>
    )
}
