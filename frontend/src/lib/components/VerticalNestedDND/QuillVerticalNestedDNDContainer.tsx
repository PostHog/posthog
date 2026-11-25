import React, { forwardRef } from 'react'

import { IconTrash } from '@posthog/icons'
import { Button, Text, cn } from '@posthog/quill'

import { IconDragHandle } from 'lib/lemon-ui/icons'

import type { ContainerProps, VNDNDContainerItem } from './VerticalNestedDND'

export const QuillVerticalNestedDNDContainer = forwardRef(function QuillVerticalNestedDNDContainer_<
    Item extends VNDNDContainerItem<any>,
>(
    {
        children,
        handleProps,
        onClick,
        onRemove,
        onAddChild,
        containerItemId,
        placeholder,
        style: _style,
        isDragging,
        transform,
        transition,
        renderContainerItem,
        updateContainerItem,
        item,
        renderAddChildItem,
        ...props
    }: ContainerProps<Item>,
    ref: React.ForwardedRef<HTMLDivElement>
) {
    const Component = onClick ? 'button' : 'div'

    return (
        <Component
            {...props}
            data-quill
            className={cn(
                'flex flex-col gap-2 overflow-hidden rounded-md border border-border bg-card p-3 text-card-foreground',
                isDragging && 'opacity-40'
            )}
            style={{
                transform,
                transition,
            }}
            ref={ref as React.ForwardedRef<HTMLButtonElement & HTMLDivElement>}
            onClick={onClick}
            tabIndex={onClick ? 0 : undefined}
        >
            <div className="flex flex-row items-start gap-2">
                <Button
                    size="icon"
                    aria-label="Drag to reorder"
                    tooltip="Drag to reorder"
                    className="cursor-grab"
                    {...handleProps}
                >
                    <IconDragHandle />
                </Button>
                <div className="min-w-0 flex-1 self-stretch">
                    {renderContainerItem ? (
                        renderContainerItem(item, { updateContainerItem })
                    ) : (
                        <Text size="xs" render={<span className="m-0 flex h-full items-center" />}>
                            {`Container ${containerItemId}`}
                        </Text>
                    )}
                </div>
                <Button
                    variant="destructive-outline"
                    size="icon"
                    aria-label="Remove"
                    tooltip="Remove"
                    onClick={onRemove}
                >
                    <IconTrash />
                </Button>
            </div>
            {placeholder ? children : <ul className="m-0 flex list-none flex-col gap-2 p-0">{children}</ul>}
            <div className="flex flex-row flex-wrap justify-end gap-2">
                {renderAddChildItem ? (
                    renderAddChildItem(item, { onAddChild })
                ) : (
                    <Button variant="outline" onClick={onRemove ? () => onAddChild(item.id) : undefined}>
                        Add child
                    </Button>
                )}
            </div>
        </Component>
    )
})
