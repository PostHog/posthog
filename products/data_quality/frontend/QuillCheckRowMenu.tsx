import { useState } from 'react'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { QuillConfirmDialog } from './QuillConfirmDialog'

export interface QuillCheckRowMenuProps {
    checkName: string
    triggerId?: string
    dataAttr: string
    onRunNow: () => void
    runDisabledReason?: string
    onEdit: () => void
    onOpenFailingRows: () => void
    onDelete: () => void
    onDeleteCancelled?: () => void
    deleteDisabledReason?: string
}

export function QuillCheckRowMenu({
    checkName,
    triggerId,
    dataAttr,
    onRunNow,
    runDisabledReason,
    onEdit,
    onOpenFailingRows,
    onDelete,
    onDeleteCancelled,
    deleteDisabledReason,
}: QuillCheckRowMenuProps): JSX.Element {
    const [confirmingDelete, setConfirmingDelete] = useState(false)

    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            id={triggerId}
                            size="icon"
                            aria-label={`Actions for check ${checkName}`}
                            className="text-muted-foreground"
                            data-attr={dataAttr}
                        />
                    }
                >
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={onRunNow} disabledReason={runDisabledReason}>
                        Run now
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={onEdit}>Edit</DropdownMenuItem>
                    <DropdownMenuItem
                        onClick={onOpenFailingRows}
                        description="The query behind this check's latest run"
                    >
                        Open failing rows in SQL editor
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                        variant="destructive"
                        onClick={() => setConfirmingDelete(true)}
                        disabledReason={deleteDisabledReason}
                    >
                        Delete
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            <QuillConfirmDialog
                open={confirmingDelete}
                title="Delete this check?"
                description="Past run history is kept."
                confirmLabel="Delete"
                onConfirm={() => {
                    setConfirmingDelete(false)
                    onDelete()
                }}
                onCancel={() => {
                    setConfirmingDelete(false)
                    onDeleteCancelled?.()
                }}
                dataAttr="data-quality-delete-check"
            />
        </>
    )
}
