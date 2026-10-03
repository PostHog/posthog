import { PreviewCard } from '@base-ui/react/preview-card'
import { type ReactNode, useState } from 'react'

import { IconArrowRight, IconSparkles } from '@posthog/icons'
import { Button, Card, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import {
    HOVER_CARD_GAP_PX,
    HOVER_CLOSE_DELAY_MS,
    HOVER_OPEN_DELAY_MS,
    cardAnchor,
    pointerMovedRecently,
} from './todayHoverCard'
import type { TodayKeyClause, TodayReadingRole } from './todayKeyClauses'

const ROLE_LABEL: Record<TodayReadingRole, string> = {
    problem: 'The problem',
    cause: 'The cause',
    fix: 'The fix',
}

export function TodayKeyClauseMark({
    keyClause,
    reportId,
    children,
}: {
    keyClause: TodayKeyClause
    reportId: string
    children: ReactNode
}): JSX.Element {
    const [trigger, setTrigger] = useState<HTMLElement | null>(null)
    const [open, setOpen] = useState(false)
    return (
        <PreviewCard.Root
            open={open}
            onOpenChange={(next, details) => {
                if (next && details.reason === 'trigger-hover' && !pointerMovedRecently()) {
                    return
                }
                setOpen(next)
            }}
        >
            <PreviewCard.Trigger
                delay={HOVER_OPEN_DELAY_MS}
                closeDelay={HOVER_CLOSE_DELAY_MS}
                ref={setTrigger}
                render={<span tabIndex={0} />}
                onClick={() => setOpen(true)}
                className="TodayKeyClause"
                data-attr={`today-report-key-${keyClause.role}`}
            >
                {children}
            </PreviewCard.Trigger>
            <PreviewCard.Portal>
                <PreviewCard.Positioner
                    data-quill
                    data-quill-portal="popover"
                    className="[--quill-z-popover:var(--z-popover-with-chart)]"
                    anchor={cardAnchor(trigger)}
                    side="bottom"
                    align="start"
                    sideOffset={HOVER_CARD_GAP_PX}
                >
                    <PreviewCard.Popup className="TodayEvidencePopup outline-none">
                        <Card
                            size="sm"
                            className="TodayEvidenceCard w-[var(--anchor-width)] gap-0 border border-border py-0"
                        >
                            <div className="flex flex-col gap-2 p-3">
                                <Text size="xs" variant="muted" render={<div />} className="flex items-center gap-1.5">
                                    <IconSparkles className="size-3.5" aria-hidden />
                                    <span className="font-medium text-[var(--foreground)]">
                                        {ROLE_LABEL[keyClause.role]}
                                    </span>
                                    <span aria-hidden>·</span>
                                    <span>AI picked this because the full report explains it further</span>
                                </Text>
                                <Text
                                    size="sm"
                                    render={<blockquote />}
                                    className="m-0 flex flex-col gap-1.5 border-l-2 border-solid ps-3 text-pretty text-[var(--foreground)]"
                                >
                                    {keyClause.expansion.map((sentence) => (
                                        <span key={sentence}>{sentence}</span>
                                    ))}
                                </Text>
                                <Button
                                    variant="link"
                                    size="sm"
                                    className="self-start px-0"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={urls.inboxReport('reports', reportId)} />}
                                    data-attr="today-report-key-full-report"
                                >
                                    Open the full report
                                    <IconArrowRight />
                                </Button>
                            </div>
                        </Card>
                    </PreviewCard.Popup>
                </PreviewCard.Positioner>
            </PreviewCard.Portal>
        </PreviewCard.Root>
    )
}
