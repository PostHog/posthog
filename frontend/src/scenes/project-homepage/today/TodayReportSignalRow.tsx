import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconChevronDown, IconExternal, IconPlay } from '@posthog/icons'
import { Item, ItemActions, ItemContent, ItemTitle, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

import type { SignalPreviewApi, SignalViewApi } from 'products/today/frontend/generated/api.schemas'

import { TodaySignalDestination, previewOpen, shownPreview, signalDestination } from './todayEvidence'
import { TodayEvidenceDetail } from './TodayEvidenceDetail'
import { TodayIcon } from './TodayIcon'
import { shortDate } from './todayProse'
import { todayReportLogic } from './todayReportLogic'
import { sourceStyle } from './todaySignalReports'
import { signalSourceLabel } from './todaySignalText'

const EXPAND: TodaySignalDestination = { kind: 'read' }

interface RowHint {
    label: string
    icon: JSX.Element
}

function rowHint(action: TodaySignalDestination, preview: SignalPreviewApi | null, expanded: boolean): RowHint | null {
    if (action.kind === 'recording') {
        return { label: 'Play', icon: <IconPlay /> }
    }
    if (action.kind === 'link') {
        return { label: action.label, icon: <IconExternal /> }
    }
    if (!preview) {
        return null
    }
    return {
        label: expanded ? 'Close' : preview.hint,
        icon: <IconChevronDown className={cn('transition-transform duration-200', expanded && 'rotate-180')} />,
    }
}

function rowElement(action: TodaySignalDestination, hint: RowHint | null, expanded: boolean): JSX.Element {
    if (action.kind === 'link') {
        return <LinkPrimitive to={action.to} target={action.external ? '_blank' : undefined} />
    }
    if (!hint) {
        return <div />
    }
    return <button type="button" aria-expanded={action.kind === 'read' ? expanded : undefined} />
}

function RowTrailer({
    signal,
    hint,
    sourceLabel,
}: {
    signal: SignalViewApi
    hint: RowHint | null
    sourceLabel: string
}): JSX.Element {
    const time = dayjs(signal.timestamp)
    return (
        <Text size="xs" variant="muted" render={<span />} className="flex items-center gap-2 whitespace-nowrap">
            <span aria-hidden className="flex size-3.5 items-center justify-center [&_svg]:size-3.5">
                <span title={sourceLabel} className={cn('flex', hint && 'group-hover/row:hidden')}>
                    <TodayIcon icon={signal.cited ?? sourceStyle(signal.source_product).icon} />
                </span>
                {hint && <span className="hidden text-[var(--foreground)] group-hover/row:flex">{hint.icon}</span>}
            </span>
            <time dateTime={signal.timestamp} title={time.format('LLL')} className="w-12 text-right tabular-nums">
                {time.isSame(dayjs(), 'day') ? 'Today' : shortDate(time)}
            </time>
        </Text>
    )
}

export function TodayReportSignalRow({ reportId, signal }: { reportId: string; signal: SignalViewApi }): JSX.Element {
    const logic = todayReportLogic({ reportId })
    const { expandedEvidence } = useValues(logic)
    const { evidenceOpened, readCode, expandEvidence, collapseEvidence } = useActions(logic)
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const expanded = !!expandedEvidence[signal.signal_id]
    const destination = useMemo(() => signalDestination(signal), [signal])
    const open = previewOpen(signal, destination)
    const preview = shownPreview(signal, open)
    const action = preview ? EXPAND : destination
    const hint = rowHint(action, preview, expanded)
    const sourceLabel = signalSourceLabel(signal)
    const detailId = `today-signal-${signal.signal_id}`

    const onClick = (): void => {
        if (!hint) {
            return
        }
        if (expanded) {
            collapseEvidence(signal.signal_id)
            return
        }
        evidenceOpened(signal, signal.cited ?? action.kind)
        if (action.kind === 'recording') {
            openSessionPlayer({ id: action.sessionId }, action.startAt)
        }
        if (action.kind !== 'read') {
            return
        }
        if (preview?.code.length) {
            readCode(signal, preview.code)
        }
        expandEvidence(signal.signal_id)
    }

    return (
        <div className={cn('rounded-md transition-colors duration-150', expanded && 'bg-[var(--today-soft)]')}>
            <Item
                variant="default"
                size="sm"
                render={rowElement(action, hint, expanded)}
                onClick={onClick}
                aria-controls={expanded ? detailId : undefined}
                className={cn(
                    'group/row w-full rounded-md border-0 px-2 py-2 text-left text-foreground no-underline',
                    expanded && 'hover:bg-transparent',
                    !hint && 'cursor-default'
                )}
                title={hint?.label}
                data-attr="today-report-signal"
            >
                <ItemContent className="min-w-0">
                    <ItemTitle
                        className={cn('font-normal text-[var(--foreground)]', !expanded && 'line-clamp-2')}
                        title={[sourceLabel, signal.meta].filter(Boolean).join(' · ')}
                    >
                        {expanded ? signal.lead : signal.headline}
                    </ItemTitle>
                </ItemContent>
                <ItemActions className="shrink-0 self-start pt-0.5">
                    <RowTrailer signal={signal} hint={hint} sourceLabel={sourceLabel} />
                </ItemActions>
            </Item>
            {expanded && preview && (
                <TodayEvidenceDetail id={detailId} reportId={reportId} signal={signal} preview={preview} open={open} />
            )}
        </div>
    )
}
