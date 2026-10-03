import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconArrowRight, IconChevronDown, IconExternal, IconPlay } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemTitle, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { TodayEvidencePreview } from './TodayEvidencePreview'
import { TodayIcon } from './TodayIcon'
import { codeFileKey, todayReportLogic } from './todayReportLogic'
import {
    TodayCodeExcerpt,
    codeIdentifiers,
    scoutLabel,
    signalCodeFile,
    signalDestination,
    signalHeadline,
    signalMeta,
    signalReading,
    signalSlackThread,
} from './todayReportPresentation'
import { chooseCodeExcerpt, signalPreview } from './todaySignalPreview'
import { sourceStyle } from './todaySignalReports'

const PLAYER_LEAD_IN_MS = 5000
const NO_CANDIDATES: TodayCodeExcerpt[] = []

export function TodayReportSignalRow({
    reportId,
    signal,
    showSource,
}: {
    reportId: string
    signal: SignalNodeApi
    showSource: boolean
}): JSX.Element {
    const { evidenceOpened, loadCodeFile, chooseExcerpt } = useActions(todayReportLogic({ reportId }))
    const { codeFiles, excerptChoices, jevEnabled } = useValues(todayReportLogic({ reportId }))
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const [reading, setReading] = useState(false)
    const codeFile = signalCodeFile(signal)
    const slackThread = signalSlackThread(signal)
    const preview = useMemo(() => signalPreview(signal), [signal])
    const destination = preview ? ({ kind: 'read' } as const) : signalDestination(signal)
    const source = sourceStyle(signal.source_product)
    const skill = (signal.extra as { skill_name?: unknown } | null)?.skill_name
    const sourceLabel =
        signal.source_product === 'signals_scout'
            ? (scoutLabel(typeof skill === 'string' ? skill : null) ?? source.label)
            : source.label
    const meta = signalMeta(signal)
    const readable = destination.kind === 'read'
    const time = dayjs(signal.timestamp)

    const hint =
        destination.kind === 'recording'
            ? { label: 'Play', icon: <IconPlay /> }
            : destination.kind === 'link'
              ? { label: destination.label, icon: <IconExternal /> }
              : readable
                ? {
                      label: reading ? 'Close' : (preview?.hint ?? 'Read in full'),
                      icon: (
                          <IconChevronDown
                              className={cn('transition-transform duration-200', reading && 'rotate-180')}
                          />
                      ),
                  }
                : null

    const render =
        destination.kind === 'link' ? (
            <LinkPrimitive to={destination.to} target={destination.external ? '_blank' : undefined} />
        ) : hint ? (
            <button type="button" aria-expanded={readable ? reading : undefined} />
        ) : (
            <div />
        )

    const onClick = (): void => {
        if (!hint) {
            return
        }
        evidenceOpened(signal, codeFile ? 'code' : slackThread ? 'slack' : destination.kind)
        if (destination.kind === 'recording') {
            openSessionPlayer(
                { id: destination.sessionId },
                destination.timestamp ? Math.max(destination.timestamp - PLAYER_LEAD_IN_MS, 0) : null
            )
        } else if (readable) {
            if (!reading) {
                preview?.code.forEach((file) => loadCodeFile(file))
            }
            setReading(!reading)
        }
    }

    const opened = readable ? signalReading(signal) : null
    const codeName = codeFile?.path.split('/').pop()
    const detailId = `today-signal-${signal.signal_id}`
    const best = useMemo(
        () =>
            preview?.code.length
                ? chooseCodeExcerpt(
                      preview.code,
                      preview.code.map((file) => codeFiles[codeFileKey(file)]),
                      codeIdentifiers(signal.content)
                  )
                : null,
        [preview, codeFiles, signal.content]
    )
    const ready = best && best !== 'loading' ? best : null
    const candidates = ready?.candidates ?? NO_CANDIDATES
    const choiceKey = ready ? `${signal.signal_id}:${ready.file.path}` : null
    const choice = choiceKey ? excerptChoices[choiceKey] : undefined
    const needsChoice = jevEnabled && candidates.length > 1
    const choiceLoading = needsChoice && (choice === undefined || choice === 'pending')
    const askForChoice = reading && needsChoice && choice === undefined
    const chosen =
        ready && needsChoice
            ? choiceLoading
                ? 'loading'
                : { ...ready, excerpt: candidates[typeof choice === 'number' ? choice : 0] ?? ready.excerpt }
            : best

    useEffect(() => {
        if (askForChoice && choiceKey) {
            chooseExcerpt(
                choiceKey,
                signal.content,
                candidates.map((candidate) => candidate.lines.join('\n'))
            )
        }
    }, [askForChoice, choiceKey, candidates, chooseExcerpt, signal.content])
    const open = preview?.code.length ? (chosen === null ? preview.open : null) : (preview?.open ?? null)
    const facts = [sourceLabel, ...(preview?.facts ?? []).filter((fact) => fact !== sourceLabel && fact !== codeName)]

    return (
        <div className={cn('rounded-md transition-colors duration-150', reading && 'bg-[var(--today-soft)]')}>
            <Item
                variant="default"
                size="sm"
                render={render}
                onClick={onClick}
                aria-controls={readable ? detailId : undefined}
                className={cn(
                    'group/row w-full rounded-md border-0 px-2 py-2 text-left text-foreground no-underline',
                    reading && 'hover:bg-transparent',
                    !hint && 'cursor-default'
                )}
                title={hint?.label}
                data-attr="today-report-signal"
            >
                <ItemContent className="min-w-0">
                    <ItemTitle
                        className={cn('font-normal text-[var(--foreground)]', !reading && 'line-clamp-2')}
                        title={[sourceLabel, meta].filter(Boolean).join(' · ')}
                    >
                        {reading && opened ? opened.lead : signalHeadline(signal)}
                    </ItemTitle>
                </ItemContent>
                <ItemActions className="shrink-0 self-start pt-0.5">
                    <Text
                        size="xs"
                        variant="muted"
                        render={<span />}
                        className="flex items-center gap-2 whitespace-nowrap"
                    >
                        <span aria-hidden className="flex size-3.5 items-center justify-center [&_svg]:size-3.5">
                            {showSource && (
                                <span title={sourceLabel} className={cn('flex', hint && 'group-hover/row:hidden')}>
                                    <TodayIcon icon={codeFile ? 'code' : slackThread ? 'slack' : source.icon} />
                                </span>
                            )}
                            {hint && (
                                <span className="hidden text-[var(--foreground)] group-hover/row:flex">
                                    {hint.icon}
                                </span>
                            )}
                        </span>
                        <time
                            dateTime={signal.timestamp}
                            title={time.format('LLL')}
                            className="w-12 text-right tabular-nums"
                        >
                            {time.isSame(dayjs(), 'day') ? 'Today' : time.format('D MMM')}
                        </time>
                    </Text>
                </ItemActions>
            </Item>
            {reading && opened && preview && (
                <div id={detailId} className="TodaySignalReading">
                    <div className="flex min-h-0 flex-col gap-2 overflow-hidden px-2 pb-3">
                        <TodayEvidencePreview preview={preview} chosen={chosen} />
                        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                            <Text size="xs" variant="muted" render={<p />} className="min-w-0">
                                {facts.join(' · ')}
                                {' · '}
                                <time dateTime={signal.timestamp}>
                                    {time.format(time.isSame(dayjs(), 'year') ? 'D MMM, HH:mm' : 'D MMM YYYY, HH:mm')}
                                </time>
                            </Text>
                            {open ? (
                                <Button
                                    variant="link-muted"
                                    size="sm"
                                    className="-me-2 px-2"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive to={open.to} target={open.external ? '_blank' : undefined} />
                                    }
                                    data-attr={slackThread ? 'today-report-signal-slack' : 'today-report-signal-open'}
                                >
                                    {open.label}
                                    {open.external ? <IconExternal /> : <IconArrowRight />}
                                </Button>
                            ) : (
                                !preview.code.length && (
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
                                )
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
