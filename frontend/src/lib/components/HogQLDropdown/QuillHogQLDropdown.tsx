import { useState } from 'react'

import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'
import { escapeDottedHogQLIdentifier } from 'lib/utils/hogql'

import { NodeKind } from '~/queries/schema/schema-general'

import { HogQLEditor } from '../HogQLEditor/HogQLEditor'

export function QuillHogQLDropdown({
    hogQLValue,
    onHogQLValueChange,
    tableName,
    hogQLEditorPlaceholder,
    connectionId,
}: {
    hogQLValue: string
    onHogQLValueChange: (hogQLValue: string) => void
    tableName: string
    hogQLEditorPlaceholder?: string
    connectionId?: string
}): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <div className="flex-auto min-w-0">
            <Popover
                open={open}
                onOpenChange={(next, details) => {
                    if (closesIntoLemonPopover(next, details)) {
                        details.cancel()
                        return
                    }

                    setOpen(next)
                }}
            >
                <PopoverTrigger render={<Button variant="outline" left className="w-full min-w-0" />}>
                    <code className="truncate">{hogQLValue}</code>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-120 max-w-(--available-width) p-2">
                    {/* The editor is Lemon, so it keeps Lemon's colors inside the quill popover. */}
                    <div data-not-quill>
                        <HogQLEditor
                            value={hogQLValue}
                            metadataSource={{
                                kind: NodeKind.HogQLQuery,
                                query: `SELECT * FROM ${escapeDottedHogQLIdentifier(tableName)}`,
                                connectionId,
                            }}
                            onChange={(currentValue) => {
                                onHogQLValueChange(currentValue)
                                setOpen(false)
                            }}
                            placeholder={hogQLEditorPlaceholder}
                        />
                    </div>
                </PopoverContent>
            </Popover>
        </div>
    )
}
