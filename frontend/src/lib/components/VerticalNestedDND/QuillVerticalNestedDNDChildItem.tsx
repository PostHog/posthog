import React from 'react'

import { IconTrash } from '@posthog/icons'
import { Button, Text, cn } from '@posthog/quill'

import { IconDragHandle } from 'lib/lemon-ui/icons'

import type { ChildItemProps } from './VerticalNestedDND'

export const QuillVerticalNestedDNDChildItem = React.forwardRef<
    HTMLLIElement,
    Pick<
        ChildItemProps<any>,
        | 'isDragging'
        | 'handleProps'
        | 'listeners'
        | 'onRemove'
        | 'childItemId'
        | 'renderChildItem'
        | 'updateChildItem'
        | 'item'
    >
>(function QuillVerticalNestedDNDChildItem_(
    { isDragging, handleProps, listeners, onRemove, childItemId, renderChildItem, updateChildItem, item, ...props },
    ref
): JSX.Element {
    return (
        <li
            ref={ref}
            data-quill
            className={cn(
                'flex overflow-hidden rounded-md border border-border bg-card p-2 text-card-foreground',
                isDragging && 'opacity-40'
            )}
        >
            <div {...props} className="flex w-full flex-row items-start gap-2">
                <Button
                    size="icon"
                    aria-label="Drag to reorder"
                    tooltip="Drag to reorder"
                    className="cursor-grab"
                    {...handleProps}
                    {...listeners}
                >
                    <IconDragHandle />
                </Button>
                <div className="min-w-0 flex-1 self-stretch">
                    {renderChildItem ? (
                        renderChildItem(item, { updateChildItem })
                    ) : (
                        <Text size="xs" render={<span className="m-0 flex h-full items-center" />}>
                            {`Item ${childItemId}`}
                        </Text>
                    )}
                </div>
                <Button
                    variant="destructive-outline"
                    size="icon"
                    aria-label="Remove"
                    tooltip="Remove"
                    onClick={() => onRemove(item.id)}
                >
                    <IconTrash />
                </Button>
            </div>
        </li>
    )
})
