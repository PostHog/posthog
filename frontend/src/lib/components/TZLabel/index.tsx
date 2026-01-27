import './index.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { forwardRef, useCallback, useEffect, useMemo, useState } from 'react'

import { IconClock, IconCopy, IconGear, IconHome, IconLaptop } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonDropdownProps } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { IconLinux, IconWeb } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime, shortTimeZone } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { teamLogic } from '../../../scenes/teamLogic'

const BASE_OUTPUT_FORMAT = 'ddd, MMM D, YYYY h:mm A'
const BASE_OUTPUT_FORMAT_WITH_SECONDS = 'ddd, MMM D, YYYY h:mm:ss A'

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
}

const TZLabelPopoverContent = React.memo(function TZLabelPopoverContent({
    showSeconds,
    time,
    title,
    displayTimezone,
}: Pick<TZLabelProps, 'showSeconds' | 'title' | 'displayTimezone'> & { time: dayjs.Dayjs }): JSX.Element {
    const DATE_OUTPUT_FORMAT = !showSeconds ? BASE_OUTPUT_FORMAT : BASE_OUTPUT_FORMAT_WITH_SECONDS
    const { currentTeam } = useValues(teamLogic)
    const { reportTimezoneComponentViewed } = useActions(eventUsageLogic)

    const copyDateTime = (dateTime: dayjs.Dayjs, label: string): void => {
        void copyToClipboard(dateTime.toDate().toISOString(), label)
    }

    const copyUnixTimestamp = (unixTimestamp: number, label: string): void => {
        void copyToClipboard(unixTimestamp.toString(), label)
    }

    const safeTimezone = (tz: string): dayjs.Dayjs => {
        try {
            return time.tz(tz)
        } catch {
            return time
        }
    }

    useOnMountEffect(() => {
        reportTimezoneComponentViewed('label', currentTeam?.timezone, shortTimeZone())
    })

    const displayedTime = displayTimezone ? safeTimezone(displayTimezone) : null

    return (
        <div className={clsx('TZLabelPopover', showSeconds && 'TZLabelPopover--seconds')}>
            <div className="flex justify-between items-center border-b-1 p-1">
                <h4 className="mb-0 px-1">{title || 'Timezone conversion'}</h4>
                <LemonButton icon={<IconGear />} size="xsmall" to={urls.settings('project', 'date-and-time')} />
            </div>
            <div className="flex flex-col gap-1 p-2">
                {displayedTime && (
                    <TZLabelPopoverRow
                        icon={<IconClock />}
                        label="Displayed"
                        caption={shortTimeZone(displayTimezone!, time.toDate()) ?? displayTimezone!}
                        value={displayedTime.format(DATE_OUTPUT_FORMAT)}
                        onClick={() => copyDateTime(displayedTime, 'displayed timezone date')}
                    />
                )}

                <TZLabelPopoverRow
                    icon={<IconLaptop />}
                    muted={displayTimezone !== undefined}
                    label="Your device"
                    caption={shortTimeZone(undefined, time.toDate())!}
                    value={time.format(DATE_OUTPUT_FORMAT)}
                    onClick={() => copyDateTime(time, 'your device date')}
                />

                {currentTeam && (
                    <TZLabelPopoverRow
                        muted
                        icon={<IconHome />}
                        label="Project"
                        caption={shortTimeZone(currentTeam.timezone, time.toDate())!}
                        value={time.tz(currentTeam.timezone).format(DATE_OUTPUT_FORMAT)}
                        onClick={() => copyDateTime(time.tz(currentTeam.timezone), 'project timezone date')}
                    />
                )}

                {currentTeam?.timezone !== 'UTC' && (
                    <TZLabelPopoverRow
                        muted
                        icon={<IconWeb />}
                        label="UTC"
                        caption="UTC"
                        value={time.tz('UTC').format(DATE_OUTPUT_FORMAT)}
                        onClick={() => copyDateTime(time.tz('UTC'), 'UTC date')}
                    />
                )}

                <TZLabelPopoverRow
                    muted
                    monospace
                    icon={<IconLinux />}
                    label="UNIX"
                    value={time.unix().toString()}
                    onClick={() => copyUnixTimestamp(time.unix(), 'UNIX timestamp')}
                />
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

    const format = useCallback(() => {
        return formatDate || formatTime
            ? humanFriendlyDetailedTime(displayTime, formatDate, formatTime, {
                  timestampStyle: displayTimezone ? 'absolute' : timestampStyle,
              })
            : displayTime.fromNow()
    }, [formatDate, formatTime, displayTime, timestampStyle, displayTimezone])

    const [formattedContent, setFormattedContent] = useState(format())

    const { isVisible: isPageVisible } = usePageVisibility()

    // NOTE: This is an optimization to make sure we don't needlessly re-render the component every second.
    useEffect(() => {
        if (!isPageVisible) {
            return
        }

        const run = (): void => {
            const newContent = format()
            setFormattedContent((current) => (newContent !== current ? newContent : current))
        }

        const interval = setInterval(run, 1000)
        run()

        return () => clearInterval(interval)
    }, [displayTime, format, isPageVisible])

    const innerContent = children ?? (
        <span
            className={
                !noStyles
                    ? clsx('whitespace-nowrap align-middle', showPopover && 'border-dotted border-b', className)
                    : className
            }
            ref={ref}
        >
            {formattedContent}
        </span>
    )

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
