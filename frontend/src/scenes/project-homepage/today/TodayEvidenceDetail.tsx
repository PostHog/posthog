import { useValues } from 'kea'

import { IconArrowRight, IconExternal } from '@posthog/icons'
import { Button, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { TodayCodeExcerpt } from './TodayCodeExcerpt'
import { citedSource } from './todayEvidence'
import { TodayCodeQuoteState, todayReportLogic } from './todayReportLogic'
import { TodayPreviewLink, TodaySignalPreview } from './todaySignalPreview'
import { signalSourceLabel } from './todaySignalText'

function quoteState(stored: TodayCodeQuoteState | undefined): TodayCodeQuoteState {
    return stored === undefined ? 'loading' : stored
}

function previewLink(preview: TodaySignalPreview, quote: TodayCodeQuoteState | null): TodayPreviewLink | null {
    return preview.code.length > 0 && quote !== null ? null : preview.open
}

export function TodayEvidenceDetail({
    id,
    reportId,
    signal,
    preview,
}: {
    id: string
    reportId: string
    signal: SignalNodeApi
    preview: TodaySignalPreview
}): JSX.Element {
    const { codeQuotes } = useValues(todayReportLogic({ reportId }))
    const quote = preview.code.length ? quoteState(codeQuotes[signal.signal_id]) : null
    const open = previewLink(preview, quote)
    const facts = [signalSourceLabel(signal), ...preview.facts]
    const linksToReport = !open && !preview.code.length
    const time = dayjs(signal.timestamp)

    return (
        <div id={id} className="TodayEvidenceDetail">
            <div className="flex min-h-0 flex-col gap-2 overflow-hidden px-2 pb-3">
                {quote && <TodayCodeExcerpt file={preview.code[0]} quote={quote} />}
                {preview.block.length > 0 && (
                    <pre
                        className="TodayCodeExcerpt TodayCodeExcerpt__body m-0 rounded-md border px-3 py-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap"
                        data-attr="today-report-signal-block"
                    >
                        {preview.block.map((line, index) => (
                            <div key={index} className={cn(line.quiet && 'text-muted-foreground')}>
                                {line.text}
                            </div>
                        ))}
                    </pre>
                )}
                {preview.text && (
                    <Text size="sm" render={<p />} className="TodayEvidenceDetail__text leading-relaxed text-pretty">
                        {preview.text}
                    </Text>
                )}
                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <Text size="xs" variant="muted" render={<p />} className="min-w-0">
                        {facts.join(' · ')}
                        {' · '}
                        <time dateTime={signal.timestamp}>
                            {time.format(time.isSame(dayjs(), 'year') ? 'D MMM, HH:mm' : 'D MMM YYYY, HH:mm')}
                        </time>
                    </Text>
                    {open && (
                        <Button
                            variant="link-muted"
                            size="sm"
                            className="-me-2 px-2"
                            nativeButton={false}
                            render={<LinkPrimitive to={open.to} target={open.external ? '_blank' : undefined} />}
                            data-attr={
                                citedSource(signal) === 'slack'
                                    ? 'today-report-signal-slack'
                                    : 'today-report-signal-open'
                            }
                        >
                            {open.label}
                            {open.external ? <IconExternal /> : <IconArrowRight />}
                        </Button>
                    )}
                    {linksToReport && (
                        <Button
                            variant="link-muted"
                            size="sm"
                            className="-me-2 px-2"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.inboxReport('reports', reportId)} />}
                            data-attr="today-report-signal-full-report"
                        >
                            Open in the full report
                            <IconArrowRight />
                        </Button>
                    )}
                </div>
            </div>
        </div>
    )
}
