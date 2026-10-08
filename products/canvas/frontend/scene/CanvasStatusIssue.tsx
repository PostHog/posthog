import { ReactNode } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { Badge, Button, Heading, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

export interface CanvasStatusIssueProps {
    /** The status, for example "Build failed". */
    label: string
    title: string
    description: string
    /** Error lines to show in full, such as build diagnostics or the thrown message. */
    details: string[]
    /** The ways out of the issue, shown at the bottom of the popover. */
    actions: ReactNode
    dataAttr: string
}

/** A problem with the canvas in the header: a status badge that opens what went wrong and how to fix it. */
export function CanvasStatusIssue({
    label,
    title,
    description,
    details,
    actions,
    dataAttr,
}: CanvasStatusIssueProps): JSX.Element {
    return (
        <Popover>
            <PopoverTrigger
                render={
                    <Button size="sm" variant="default" aria-label={`${label}. Show details`} data-attr={dataAttr} />
                }
            >
                <Badge variant="destructive">{label}</Badge>
                <IconChevronDown />
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 max-w-full gap-3">
                <div className="flex flex-col gap-1">
                    <Heading render={<h2 />} size="sm">
                        {title}
                    </Heading>
                    <Text size="xs" variant="muted">
                        {description}
                    </Text>
                </div>
                {details.length > 0 && (
                    <ul className="flex max-h-48 flex-col gap-1 overflow-y-auto rounded-sm border border-border p-2">
                        {details.map((detail, index) => (
                            <Text
                                key={index}
                                size="xs"
                                render={<li />}
                                className="font-mono break-words whitespace-pre-wrap"
                                translate="no"
                            >
                                {detail}
                            </Text>
                        ))}
                    </ul>
                )}
                <div className="flex flex-wrap justify-end gap-2">{actions}</div>
            </PopoverContent>
        </Popover>
    )
}
