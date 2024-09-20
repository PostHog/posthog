import './index.scss'

import { IconGear, IconHome, IconLaptop } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonDropdownProps } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { IconWeb } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime, shortTimeZone } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { forwardRef } from 'react'
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
    children?: JSX.Element
}

const TZLabelPopoverContent = React.memo(function TZLabelPopoverContent({
    showSeconds,
    time,
}: Pick<TZLabelProps, 'showSeconds'> & { time: dayjs.Dayjs }): JSX.Element {
    const DATE_OUTPUT_FORMAT = !showSeconds ? BASE_OUTPUT_FORMAT : BASE_OUTPUT_FORMAT_WITH_SECONDS
    const { currentTeam } = useValues(teamLogic)
    const { reportTimezoneComponentViewed } = useActions(eventUsageLogic)

    useEffect(() => {
        reportTimezoneComponentViewed('label', currentTeam?.timezone, shortTimeZone())
    }, [])

    return (
        <div className={clsx('TZLabelPopover', showSeconds && 'TZLabelPopover--seconds')}>
            <div className="flex justify-between items-center">
                <h3 className="mb-0">Timezone conversion</h3>
                <span>
                    <LemonButton icon={<IconGear />} size="small" to={urls.settings('project', 'date-and-time')} />
                </span>
            </div>

            <LemonDivider />

            <div className="space-y-2">
                <div className="TZLabelPopover__row">
                    <div>
                        <IconLaptop />
                    </div>
                    <div>Your device</div>
                    <div>{shortTimeZone(undefined, time.toDate())}</div>
                    <div>{time.format(DATE_OUTPUT_FORMAT)}</div>
                </div>
                {currentTeam && (
                    <div className="TZLabelPopover__row TZLabelPopover__row--muted">
                        <div>
                            <IconHome />
                        </div>
                        <div>Project</div>
                        <div>{shortTimeZone(currentTeam.timezone, time.toDate())}</div>
                        <div>{time.tz(currentTeam.timezone).format(DATE_OUTPUT_FORMAT)}</div>
                    </div>
                )}
                {currentTeam?.timezone !== 'UTC' && (
                    <div className="TZLabelPopover__row TZLabelPopover__row--muted">
                        <div>
                            <IconWeb />
                        </div>
                        <div />
                        <div>UTC</div>
                        <div>{time.tz('UTC').format(DATE_OUTPUT_FORMAT)}</div>
                    </div>
                )}
            </div>
        </div>
    )
})

/** Return a simple label component with timezone conversion UI. */

const TZLabelRaw = forwardRef<HTMLElement, TZLabelProps>(function TZLabelRaw(
    {
        time,
        showSeconds,
        formatDate,
        formatTime,
        showPopover = true,
        noStyles = false,
        className,
        children,
        ...dropdownProps
    },
    ref
): JSX.Element {
    const parsedTime = useMemo(() => (dayjs.isDayjs(time) ? time : dayjs(time)), [time])

    const format = useCallback(() => {
        return formatDate || formatTime
            ? humanFriendlyDetailedTime(parsedTime, formatDate, formatTime)
            : parsedTime.fromNow()
    }, [formatDate, formatTime, parsedTime])

    const [formattedContent, setFormattedContent] = useState(format())

    useEffect(() => {
        // NOTE: This is an optimization to make sure we don't needlessly re-render the component every second.
        const interval = setInterval(() => {
            if (format() !== formattedContent) {
                setFormattedContent(format())
            }
        }, 1000)
        return () => clearInterval(interval)
    }, [parsedTime, format])

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
                overlay={<TZLabelPopoverContent time={parsedTime} showSeconds={showSeconds} />}
            >
                {innerContent}
            </LemonDropdown>
        )
    }

    return innerContent
})
// Timezone calculations are quite expensive, so the component is memoized to reduce them.
export const TZLabel = React.memo(TZLabelRaw) as typeof TZLabelRaw
