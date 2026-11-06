import { useState } from 'react'

import { IconCheck, IconCopy } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { writeToClipboard } from 'lib/utils/writeToClipboard'

export function CopyBlock({
    text,
    label,
    wrap = false,
    dataAttr,
}: {
    text: string
    /** Names what is copied, for the button's accessible name. */
    label: string
    /** Prompts wrap; commands stay on one line. */
    wrap?: boolean
    dataAttr?: string
}): JSX.Element {
    const [copied, setCopied] = useState(false)

    return (
        <div
            className="flex items-start gap-2 rounded-md border border-border bg-muted py-1.5 pl-3 pr-1.5"
            data-attr={dataAttr}
        >
            <code
                className={cn(
                    'min-w-0 flex-1 py-1 font-mono text-xs text-foreground',
                    wrap ? 'whitespace-pre-wrap break-words' : 'truncate'
                )}
            >
                {text}
            </code>
            <Button
                size="icon-sm"
                aria-label={`Copy ${label}`}
                tooltip={copied ? 'Copied' : `Copy ${label}`}
                onClick={() => {
                    void writeToClipboard(text).then((outcome) => {
                        if (outcome === 'copied') {
                            setCopied(true)
                            setTimeout(() => setCopied(false), 2000)
                        }
                    })
                }}
            >
                {copied ? <IconCheck /> : <IconCopy />}
            </Button>
        </div>
    )
}
