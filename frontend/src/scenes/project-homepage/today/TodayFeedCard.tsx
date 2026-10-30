import { type CSSProperties, type MouseEvent, type ReactNode, Suspense, lazy, useEffect, useRef } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Button, IconStack, IconStackItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { retryImport } from 'lib/utils/retryImport'

import type { TodayRowTone } from './TodayRow'
import type { TodayRowIcon } from './todayRowIcons'
import { isPlainClick, navigateWithCrossfade } from './todayViewTransition'

const TodaySparkline = lazy(() =>
    retryImport(() => import('./TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

export interface TodayFeedCardTracking {
    /** Fires once the pointer rests on the card. */
    onDwell: () => void
    /** Fires with the `data-attr` of whatever the person clicks inside the card. */
    onInteract: (target: string) => void
}

interface TodayFeedCardProps {
    icon: TodayRowIcon
    source: string
    title: string
    tone: TodayRowTone
    priority?: string | null
    meta?: string | null
    quote?: string | null
    lead?: string | null
    figure?: { value: string; label: string } | null
    series?: number[] | null
    chips?: ReactNode
    secondaryActions?: ReactNode
    /** Where the title and the primary action go. */
    open?: { to: string; label: string; onOpen: () => void; crossfade?: boolean }
    /** The primary action when the card has nowhere to link to. */
    fallbackAction?: ReactNode
    done?: boolean
    dataAttr: string
    tracking?: TodayFeedCardTracking
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
}: TodayFeedCardProps): JSX.Element {
    const dwellTimer = useRef<number>()
    useEffect(() => () => window.clearTimeout(dwellTimer.current), [])
    const shownPriority = tone === 'risk' ? priority : null
    const link = open
        ? {
              to: open.to,
              target: /^https?:\/\//.test(open.to) ? '_blank' : undefined,
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
                dwellTimer.current = window.setTimeout(() => tracking?.onDwell(), DWELL_MS)
            }}
            onPointerLeave={() => window.clearTimeout(dwellTimer.current)}
            onClickCapture={(event) => {
                const target = (event.target as HTMLElement).closest('[data-attr]')?.getAttribute('data-attr')
                tracking?.onInteract(target ?? `${dataAttr}-card`)
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
                        <LinkPrimitive {...link} data-attr={dataAttr}>
                            {title}
                        </LinkPrimitive>
                    ) : (
                        title
                    )}
                </p>
                {(shownPriority || meta) && (
                    <p className="TodayFeedCard__meta">
                        {shownPriority && <span className="TodayFeedCard__priority">{shownPriority}</span>}
                        {shownPriority && meta && ' · '}
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
                            <strong translate="no">{figure.value}</strong> {figure.label}
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
