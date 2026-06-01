/**
 * Collapsible "thinking" aside emitted by the model before its
 * user-facing response. Click to expand.
 */

import { ChevronDownIcon, ChevronRightIcon } from 'lucide-react'
import { useState } from 'react'

interface ThinkingPartProps {
    text: string
}

export function ThinkingPart({ text }: ThinkingPartProps): React.ReactElement {
    const [open, setOpen] = useState(false)
    return (
        <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="flex w-full cursor-pointer items-start gap-1.5 rounded-md px-1.5 py-1 text-left text-xs text-muted-foreground transition-colors hover:bg-muted/30"
        >
            {open ? (
                <ChevronDownIcon className="mt-0.5 h-3 w-3 shrink-0" />
            ) : (
                <ChevronRightIcon className="mt-0.5 h-3 w-3 shrink-0" />
            )}
            <span className={open ? 'whitespace-pre-wrap' : 'line-clamp-1'}>
                <span className="font-medium text-foreground/70">Thinking · </span>
                {text}
            </span>
        </button>
    )
}
