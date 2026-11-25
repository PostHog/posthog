import type { ReactNode } from 'react'

import { IconPerson } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { cn } from 'lib/utils/css-classes'

import type { TracePreviewMissingReasonApi } from '../../generated/api.schemas'
import type { TraceSample } from '../traceSamples'

function previewText(text: string | null | undefined, reason: TracePreviewMissingReasonApi | null | undefined): string {
    if (text) {
        return text
    }
    if (reason === 'too_large') {
        return 'Too large to preview'
    }
    return reason === 'timed_out' ? "Couldn't load in time" : 'Not captured'
}

/** One trace in a list of examples: who it ran for, why it is there, and what it asked and answered. */
export function TraceSampleRow({
    sample,
    timestamp,
    tag,
    note,
    onOpen,
    'data-attr': dataAttr,
}: {
    /** Null when the row has no trace to preview, such as a cited session. */
    sample: TraceSample | null
    timestamp: string | null
    tag?: ReactNode
    /** Why the trace is an example, such as the evaluator's reasoning. */
    note: string | null
    onOpen: (() => void) | null
    'data-attr': string
}): JSX.Element {
    const preview = sample?.preview
    const person = sample?.person
    const lines: [string, string, boolean][] = [
        ['Input', previewText(preview?.input, preview?.inputMissingReason), !!preview?.input],
        ['Output', previewText(preview?.output, preview?.outputMissingReason), !!preview?.output],
    ]
    return (
        <button
            type="button"
            disabled={!onOpen}
            onClick={onOpen ?? undefined}
            // Inputs, outputs, reasoning and person labels are raw event data, so keep them out of autocapture and replay.
            className="ph-no-capture flex w-full items-start gap-3 px-3 py-2.5 text-left enabled:cursor-pointer enabled:hover:bg-fill-highlight-50"
            data-attr={dataAttr}
        >
            <Tooltip title={person?.label ?? 'Unknown person'}>
                <span className="mt-0.5 shrink-0">
                    {person ? (
                        <ProfilePicture name={person.label} size="md" />
                    ) : (
                        <span className="flex size-6 items-center justify-center rounded-full bg-fill-tertiary text-secondary">
                            <IconPerson className="size-3.5" />
                        </span>
                    )}
                </span>
            </Tooltip>
            <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="flex items-start justify-between gap-3">
                    <span className="flex min-w-0 items-start gap-2">
                        {tag ? <span className="shrink-0">{tag}</span> : null}
                        <span className="line-clamp-2 text-sm">{note}</span>
                    </span>
                    {timestamp ? (
                        <TZLabel
                            time={timestamp}
                            noStyles
                            className="shrink-0 whitespace-nowrap text-xs text-secondary"
                        />
                    ) : null}
                </span>
                {sample && (
                    <span className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                        {lines.map(([label, text, present]) => (
                            <span key={label} className="contents">
                                <span className="text-secondary">{label}</span>
                                <span className={cn('line-clamp-1 break-all', !present && 'italic text-secondary')}>
                                    {text}
                                </span>
                            </span>
                        ))}
                    </span>
                )}
            </span>
        </button>
    )
}
