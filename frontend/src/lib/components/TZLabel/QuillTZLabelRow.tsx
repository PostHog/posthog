import { useEffect, useRef, useState } from 'react'

import { IconCheck, IconCopy } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { TimezoneRow } from './timezoneRows'

const COPIED_RESET_MS = 1500

export function QuillTZLabelRow({ row }: { row: TimezoneRow }): JSX.Element {
    const { icon, label, caption, value, copyDescription, muted, monospace } = row
    const [copied, setCopied] = useState(false)
    const resetTimer = useRef<number>()

    useEffect(() => () => window.clearTimeout(resetTimer.current), [])

    const copy = async (): Promise<void> => {
        if (await copyToClipboard(value, copyDescription, { silent: true })) {
            setCopied(true)
            window.clearTimeout(resetTimer.current)
            resetTimer.current = window.setTimeout(() => setCopied(false), COPIED_RESET_MS)
        }
    }

    return (
        <Button
            left
            className={cn('w-full gap-2', muted && 'text-muted-foreground')}
            onClick={() => void copy()}
            aria-label={`Copy ${label} time, ${value}`}
            data-attr="tz-label-copy"
        >
            {icon}
            <span className="font-medium">{label}</span>
            {caption && <span className="text-xs text-muted-foreground">{caption}</span>}
            {/*
              The value and its confirmation share one grid cell, cross-faded like quill's chat swap, so the cell keeps
              the value's width and nothing in the row moves.
            */}
            <span className="ms-auto grid justify-items-end text-xs text-muted-foreground *:col-start-1 *:row-start-1">
                <span
                    className={cn(
                        'transition-[opacity,translate] duration-150 ease-[ease] motion-reduce:transition-none',
                        monospace && 'font-mono',
                        copied ? '-translate-y-0.5 opacity-0' : 'translate-y-0 opacity-100'
                    )}
                    translate={monospace ? 'no' : undefined}
                    aria-hidden={copied}
                >
                    {value}
                </span>
                <span
                    className={cn(
                        'font-medium text-success-foreground transition-[opacity,translate] duration-150 ease-[ease] motion-reduce:transition-none',
                        copied ? 'translate-y-0 opacity-100' : 'translate-y-0.5 opacity-0'
                    )}
                    aria-hidden={!copied}
                >
                    Copied!
                </span>
            </span>
            <span className="sr-only" aria-live="polite">
                {copied ? 'Copied' : ''}
            </span>
            <span className="grid shrink-0 *:col-start-1 *:row-start-1" aria-hidden>
                <IconCopy
                    className={cn(
                        'transition-[opacity,scale,filter] duration-150 ease-out motion-reduce:transition-none',
                        copied ? 'scale-50 opacity-0 blur-[2px]' : 'scale-100 opacity-100 blur-0'
                    )}
                />
                <IconCheck
                    className={cn(
                        'text-success-foreground transition-[opacity,scale,filter] duration-150 ease-out motion-reduce:transition-none',
                        copied ? 'scale-100 opacity-100 blur-0' : 'scale-50 opacity-0 blur-[2px]'
                    )}
                />
            </span>
        </Button>
    )
}
