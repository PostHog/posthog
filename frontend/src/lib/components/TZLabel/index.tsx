import './index.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { forwardRef, useCallback, useEffect, useMemo, useState } from 'react'

import { IconCopy, IconGear } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonDropdownProps } from '@posthog/lemon-ui'

import { QuillHoverCard } from 'lib/components/QuillHoverCard/QuillHoverCard'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { shortTimeZone } from 'lib/utils/timezones'
import { urls } from 'scenes/urls'

import { teamLogic } from '../../../scenes/teamLogic'
import { QuillTZLabelCard } from './QuillTZLabelCard'
import { getTimezoneRows } from './timezoneRows'

// One shared 1s ticker for every mounted TZLabel: a table can render hundreds of them, and an
// interval per instance means hundreds of timer wake-ups per second for text that changes about
// once a minute. The interval only runs while at least one label is subscribed.
const tickerListeners = new Set<() => void>()
let tickerId: number | null = null

export function subscribeToTicker(listener: () => void): () => void {
    tickerListeners.add(listener)
    if (tickerId === null) {
        tickerId = window.setInterval(() => tickerListeners.forEach((tick) => tick()), 1000)
    }
    return () => {
        tickerListeners.delete(listener)
        if (tickerListeners.size === 0 && tickerId !== null) {
            window.clearInterval(tickerId)
            tickerId = null
        }
    }
}

export type TZLabelProps = Omit<LemonDropdownProps, 'overlay' | 'trigger' | 'children'> & {
    time: string | dayjs.Dayjs
    showSeconds?: boolean
    formatDate?: string
    formatTime?: string
    /** whether to show a popover on hover - defaults to true */
    showPopover?: boolean
    noStyles?: boolean
    className?: string
    title?: string
    children?: JSX.Element
    /** 'relative' shows "Just now", "Today", "Yesterday" when applicable. 'absolute' always shows full date+time. */
    timestampStyle?: 'relative' | 'absolute'
    /** Timezone to display the time in (e.g., 'UTC', 'America/New_York'). If not set, uses local timezone.
     * Note: When set, forces timestampStyle to 'absolute' to avoid broken relative date comparisons. */
    displayTimezone?: string
    /** Custom suffix to replace "ago" in relative time display. e.g. suffix="old" renders "5 hours old" */
    suffix?: string
}

const TZLabelPopoverContent = React.memo(function TZLabelPopoverContent({
    showSeconds,
    time,
    title,
    displayTimezone,
}: Pick<TZLabelProps, 'showSeconds' | 'title' | 'displayTimezone'> & {
    time: dayjs.Dayjs
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { reportTimezoneComponentViewed } = useActions(eventUsageLogic)

    useOnMountEffect(() => {
        reportTimezoneComponentViewed('label', currentTeam?.timezone, shortTimeZone())
    })

    return (
        <div className={clsx('TZLabelPopover', showSeconds && 'TZLabelPopover--seconds')}>
            <div className="flex justify-between items-center border-b-1 p-1">
                <h4 className="mb-0 px-1">{title || 'Timezone conversion'}</h4>
                <LemonButton
                    icon={<IconGear />}
                    size="xsmall"
                    to={urls.settings('environment-customization', 'date-and-time')}
                />
            </div>
            <div className="flex flex-col gap-1 p-2">
                {getTimezoneRows(time, { showSeconds, displayTimezone, projectTimezone: currentTeam?.timezone }).map(
                    (row) => (
                        <TZLabelPopoverRow
                            key={row.key}
                            icon={row.icon}
                            label={row.label}
                            caption={row.caption}
                            value={row.value}
                            muted={row.muted}
                            monospace={row.monospace}
                            onClick={() => void copyToClipboard(row.value, row.copyDescription)}
                        />
                    )
                )}
            </div>
        </div>
    )
})

const TZLabelPopoverRow = React.memo(function TZLabelPopoverRow({
    icon,
    label,
    caption,
    value,
    onClick,
    muted = false,
    monospace = false,
}: {
    icon: React.ReactNode
    label: string
    caption?: string
    value: string
    onClick: () => void
    muted?: boolean
    monospace?: boolean
}): JSX.Element {
    return (
        <div className={clsx('TZLabelPopover__row', muted && 'TZLabelPopover__row--muted')} onClick={onClick}>
            {icon}
            <div>{label}</div>
            <div className="text-xs">{caption}</div>
            <div className={clsx('text-muted text-xs', monospace && 'font-mono')}>{value}</div>
            <IconCopy fontSize="xsmall" />
        </div>
    )
})

/** Return a simple label component with timezone conversion UI. */

const TZLabelRaw = forwardRef<HTMLElement, TZLabelProps>(function TZLabelRaw(
    {
        time,
        showSeconds,
        timestampStyle = 'relative',
        formatDate,
        formatTime,
        showPopover = true,
        noStyles = false,
        title,
        className,
        children,
        displayTimezone,
        suffix,
        ...dropdownProps
    },
    ref
): JSX.Element {
    const parsedTime = useMemo(() => (dayjs.isDayjs(time) ? time : dayjs(time)), [time])
    const displayTime = useMemo(() => {
        if (!displayTimezone) {
            return parsedTime
        }
        try {
            return parsedTime.tz(displayTimezone)
        } catch {
            return parsedTime
        }
    }, [parsedTime, displayTimezone])
    const effectiveTimestampStyle = displayTimezone ? 'absolute' : timestampStyle

    const format = useCallback(() => {
        if (formatDate || formatTime || effectiveTimestampStyle === 'absolute') {
            return humanFriendlyDetailedTime(displayTime, formatDate, formatTime, {
                timestampStyle: effectiveTimestampStyle,
            })
        }
        if (suffix) {
            return `${displayTime.fromNow(true)} ${suffix}`
        }
        return displayTime.fromNow()
    }, [formatDate, formatTime, displayTime, effectiveTimestampStyle, suffix])

    const [formattedContent, setFormattedContent] = useState(format)

    const { isVisible: isPageVisible } = usePageVisibility()
    const isQuill = useFeatureFlag('TODAY_RAIL_NAV')

    // NOTE: The guarded setState makes sure we don't needlessly re-render the component every second.
    useEffect(() => {
        if (!isPageVisible) {
            return
        }

        const run = (): void => {
            const newContent = format()
            setFormattedContent((current) => (newContent !== current ? newContent : current))
        }

        run()

        return subscribeToTicker(run)
    }, [displayTime, format, isPageVisible])

    const innerContent = children ?? (
        <span
            className={
                !noStyles
                    ? cn('whitespace-nowrap align-middle', showPopover && 'border-dotted border-b', className)
                    : className
            }
            ref={ref}
        >
            {formattedContent}
        </span>
    )

    if (showPopover && isQuill) {
        return (
            <QuillHoverCard
                arrow
                className="w-auto max-w-sm gap-0 p-0"
                content={
                    <QuillTZLabelCard
                        time={parsedTime}
                        showSeconds={showSeconds}
                        title={title}
                        displayTimezone={displayTimezone}
                    />
                }
            >
                {innerContent}
            </QuillHoverCard>
        )
    }

    if (showPopover) {
        return (
            <LemonDropdown
                placement="top"
                showArrow
                {...dropdownProps}
                trigger="hover"
                closeOnClickInside={false}
                overlay={
                    <TZLabelPopoverContent
                        time={parsedTime}
                        showSeconds={showSeconds}
                        title={title}
                        displayTimezone={displayTimezone}
                    />
                }
            >
                {innerContent}
            </LemonDropdown>
        )
    }

    return innerContent
})
// Timezone calculations are quite expensive, so the component is memoized to reduce them.
export const TZLabel = React.memo(TZLabelRaw) as typeof TZLabelRaw
