import { useActions } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconExternal, IconPlay } from '@posthog/icons'
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { TodayIcon } from './TodayIcon'
import { todayReportLogic } from './todayReportLogic'
import { signalDestination, signalHeadline } from './todayReportPresentation'
import { TodayReportProse } from './TodayReportProse'
import { sourceStyle } from './todaySignalReports'

const PLAYER_LEAD_IN_MS = 5000

export function TodayReportSignalRow({
    reportId,
    signal,
    showIcon,
}: {
    reportId: string
    signal: SignalNodeApi
    showIcon: boolean
}): JSX.Element {
    const { evidenceOpened } = useActions(todayReportLogic({ reportId }))
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const [reading, setReading] = useState(false)
    const destination = signalDestination(signal)
    const source = sourceStyle(signal.source_product)

    const description =
        destination.kind === 'recording'
            ? destination.offset
                ? `Recording at ${destination.offset}`
                : 'Recording'
            : showIcon
              ? source.label
              : null
    const hint =
        destination.kind === 'recording'
            ? { label: 'Play', icon: <IconPlay /> }
            : destination.kind === 'link'
              ? { label: destination.label, icon: <IconExternal /> }
              : { label: reading ? 'Hide' : 'Read', icon: <IconChevronDown className={cn(reading && 'rotate-180')} /> }

    const render =
        destination.kind === 'link' ? (
            <LinkPrimitive to={destination.to} target={destination.external ? '_blank' : undefined} />
        ) : (
            <button type="button" aria-expanded={destination.kind === 'read' ? reading : undefined} />
        )

    const onClick = (): void => {
        evidenceOpened(signal, destination.kind)
        if (destination.kind === 'recording') {
            openSessionPlayer(
                { id: destination.sessionId },
                destination.timestamp ? Math.max(destination.timestamp - PLAYER_LEAD_IN_MS, 0) : null
            )
        } else if (destination.kind === 'read') {
            setReading(!reading)
        }
    }

    return (
        <div>
            <Item
                variant="default"
                size="sm"
                render={render}
                onClick={onClick}
                className="group/row text-left text-foreground no-underline hover:bg-fill-hover"
                data-attr="today-report-signal"
            >
                {showIcon && (
                    <ItemMedia variant="icon" className="text-muted-foreground">
                        <TodayIcon icon={source.icon} />
                    </ItemMedia>
                )}
                <ItemContent className="min-w-0">
                    <ItemTitle className="line-clamp-2 font-normal">{signalHeadline(signal)}</ItemTitle>
                    {description && <ItemDescription>{description}</ItemDescription>}
                </ItemContent>
                <ItemActions className="shrink-0">
                    <Text size="xs" variant="muted" className="tabular-nums group-hover/row:hidden">
                        {dayjs(signal.timestamp).format('D MMM')}
                    </Text>
                    <Text
                        size="xs"
                        className="hidden items-center gap-1 font-medium group-hover/row:flex [&_svg]:size-3.5"
                    >
                        <span>{hint.label}</span>
                        {hint.icon}
                    </Text>
                </ItemActions>
            </Item>
            {reading && (
                <div className={cn('pb-3', showIcon ? 'ps-10 pe-2' : 'px-2')}>
                    <TodayReportProse markdown={signal.content} tone="body" />
                </div>
            )}
        </div>
    )
}
