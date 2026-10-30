import { type CSSProperties, type MouseEvent, type ReactNode, useEffect, useRef } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Button, IconStack, IconStackItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { isExternalLink } from 'lib/utils/url'

import { TodayFeedCardBody, type TodayFeedCardBodyProps } from './TodayFeedCardBody'
import type { TodayRowIcon } from './todayRowIcons'
import { isPlainClick, navigateWithCrossfade } from './todayViewTransition'

export interface TodayFeedCardTracking {
    onDwell: () => void
    onInteract: (target: string) => void
}

interface TodayFeedCardOpen {
    to: string
    label: string
    onOpen: () => void
    crossfade?: boolean
}

interface TodayFeedCardProps extends TodayFeedCardBodyProps {
    icon: TodayRowIcon
    source: string
    title: string
    priority?: string | null
    meta?: ReactNode
    secondaryActions?: ReactNode
    open?: TodayFeedCardOpen
    fallbackAction?: ReactNode
    done?: boolean
    dataAttr: string
    tracking?: TodayFeedCardTracking
    reportId?: string
}

const DWELL_MS = 600

interface TodayFeedCardLink {
    to: string
    target: '_blank' | undefined
    onClick: (event: MouseEvent<HTMLElement>) => void
}

function cardLink(open: TodayFeedCardOpen): TodayFeedCardLink {
    return {
        to: open.to,
        target: isExternalLink(open.to) ? '_blank' : undefined,
        onClick: (event) => {
            open.onOpen()
            if (open.crossfade && isPlainClick(event)) {
                event.preventDefault()
                navigateWithCrossfade(open.to)
            }
        },
    }
}

function useCardTracking(
    tracking: TodayFeedCardTracking | undefined,
    dataAttr: string
): Pick<JSX.IntrinsicElements['li'], 'onPointerEnter' | 'onPointerLeave' | 'onClickCapture'> {
    const dwellTimer = useRef<number>()
    const dwelled = useRef(false)
    useEffect(() => () => window.clearTimeout(dwellTimer.current), [])
    return {
        onPointerEnter: () => {
            dwellTimer.current = window.setTimeout(() => {
                if (!dwelled.current) {
                    dwelled.current = true
                    tracking?.onDwell()
                }
            }, DWELL_MS)
        },
        onPointerLeave: () => window.clearTimeout(dwellTimer.current),
        onClickCapture: (event) => {
            const found = (event.target as HTMLElement).closest('[data-attr]')
            const inside = found && event.currentTarget.contains(found)
            tracking?.onInteract((inside && found.getAttribute('data-attr')) || `${dataAttr}-card`)
        },
    }
}

export function TodayFeedCard({
    icon,
    source,
    title,
    priority,
    meta,
    secondaryActions,
    open,
    fallbackAction,
    done,
    dataAttr,
    tracking,
    reportId,
    ...body
}: TodayFeedCardProps): JSX.Element {
    const trackingProps = useCardTracking(tracking, dataAttr)
    const shownPriority = body.tone === 'risk' ? priority : null
    const link = open ? cardLink(open) : null
    return (
        <li className="TodayFeedCard" data-done={done || undefined} {...trackingProps}>
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
                <p className="TodayFeedCard__meta">
                    {shownPriority && <span className="TodayFeedCard__priority">{shownPriority}</span>}
                    {meta && <span translate="no">{meta}</span>}
                </p>
            </header>
            <TodayFeedCardBody {...body} />
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
