import { type CSSProperties, type MouseEvent, type ReactNode, Suspense, lazy, useEffect, useRef } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Button, IconStack, IconStackItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { retryImport } from 'lib/utils/retryImport'
import { isExternalLink } from 'lib/utils/url'

import type { TodayRowTone } from './TodayRow'
import type { TodayRowIcon } from './todayRowIcons'
import { isPlainClick, navigateWithCrossfade } from './todayViewTransition'

const TodaySparkline = lazy(() =>
    retryImport(() => import('./TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

export interface TodayFeedCardTracking {
    onDwell: () => void
    onInteract: (target: string) => void
}

interface TodayFeedCardProps {
    icon: TodayRowIcon
    source: string
    title: string
    tone: TodayRowTone
    priority?: string | null
    meta?: ReactNode
    quote?: string | null
    lead?: string | null
    figure?: { value: string; label: string } | null
    series?: number[] | null
    chips?: ReactNode
    secondaryActions?: ReactNode
    open?: { to: string; label: string; onOpen: () => void; crossfade?: boolean }
    fallbackAction?: ReactNode
    done?: boolean
    dataAttr: string
    tracking?: TodayFeedCardTracking
    reportId?: string
}

const DWELL_MS = 600

export function TodayFeedCard({
    icon,
    source,
    title,
    tone,
    priority,
    meta,
    quote,
    lead,
    figure,
    series,
    chips,
    secondaryActions,
    open,
    fallbackAction,
    done,
    dataAttr,
    tracking,
    reportId,
}: TodayFeedCardProps): JSX.Element {
    const dwellTimer = useRef<number>()
    const dwelled = useRef(false)
    useEffect(() => () => window.clearTimeout(dwellTimer.current), [])
    const shownPriority = tone === 'risk' ? priority : null
    const link = open
        ? {
              to: open.to,
              target: isExternalLink(open.to) ? '_blank' : undefined,
              onClick: (event: MouseEvent<HTMLElement>): void => {
                  open.onOpen()
                  if (open.crossfade && isPlainClick(event)) {
                      event.preventDefault()
                      navigateWithCrossfade(open.to)
                  }
              },
          }
        : null
    return (
        <li
            className="TodayFeedCard"
            data-done={done || undefined}
            onPointerEnter={() => {
                dwellTimer.current = window.setTimeout(() => {
                    if (!dwelled.current) {
                        dwelled.current = true
                        tracking?.onDwell()
                    }
                }, DWELL_MS)
            }}
            onPointerLeave={() => window.clearTimeout(dwellTimer.current)}
            onClickCapture={(event) => {
                const found = (event.target as HTMLElement).closest('[data-attr]')
                const inside = found && event.currentTarget.contains(found)
                tracking?.onInteract((inside && found.getAttribute('data-attr')) || `${dataAttr}-card`)
            }}
        >
            <header className="TodayFeedCard__header">
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <span
                                className="TodayFeedCard__avatar"
                                aria-label={source}
                                style={{ '--today-feed-tint': icon.color } as CSSProperties}
                            />
                        }
                    >
                        <IconStack>
                            <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
                        </IconStack>
                    </TooltipTrigger>
                    <TooltipContent side="bottom">{source}</TooltipContent>
                </Tooltip>
                <p className="TodayFeedCard__title" title={title}>
                    {link ? (
                        <LinkPrimitive {...link} data-today-report={reportId} data-attr={dataAttr}>
                            {title}
                        </LinkPrimitive>
                    ) : (
                        title
                    )}
                </p>
                {(shownPriority || meta) && (
                    <p className="TodayFeedCard__meta">
                        {shownPriority && <span className="TodayFeedCard__priority">{shownPriority}</span>}
                        {shownPriority && meta && <span> · </span>}
                        {meta && <span translate="no">{meta}</span>}
                    </p>
                )}
            </header>
            {(quote || lead || figure || series || chips) && (
                <div className="TodayFeedCard__body">
                    {quote && (
                        <p className="TodayFeedCard__quote font-mono" title={quote}>
                            {quote}
                        </p>
                    )}
                    {lead && <p className="TodayFeedCard__lead">{lead}</p>}
                    {figure && (
                        <p className="TodayFeedCard__figure">
                            <strong translate="no">{figure.value}</strong>
                            <span>{figure.label}</span>
                        </p>
                    )}
                    {series && series.length > 1 && (
                        <div className="TodayFeedCard__trend" aria-hidden>
                            <Suspense fallback={null}>
                                <TodaySparkline
                                    values={series}
                                    labels={series.map((_, index) => String(index))}
                                    tone={tone === 'risk' ? 'risk' : 'neutral'}
                                    emphasizeLast={1}
                                />
                            </Suspense>
                        </div>
                    )}
                    {chips && <div className="TodayFeedCard__chips">{chips}</div>}
                </div>
            )}
            <footer className="TodayFeedCard__actions">
                {secondaryActions}
                {link ? (
                    <Button
                        variant="link-muted"
                        size="sm"
                        nativeButton={false}
                        render={<LinkPrimitive {...link} />}
                        className="TodayFeedCard__primary"
                        data-attr={`${dataAttr}-open`}
                    >
                        <IconArrowRight />
                        {open?.label}
                    </Button>
                ) : (
                    fallbackAction
                )}
            </footer>
        </li>
    )
}
