import './index.scss'
import { useActions, useValues } from 'kea'
import { ProjectOutlined, LaptopOutlined, GlobalOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime, shortTimeZone } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from '../../../scenes/teamLogic'
import { dayjs } from 'lib/dayjs'
import clsx from 'clsx'
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { LemonButton, LemonDivider, LemonDropdown, LemonDropdownProps } from '@posthog/lemon-ui'
import { IconSettings } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

const BASE_OUTPUT_FORMAT = 'ddd, MMM D, YYYY h:mm A'

export type TZLabelProps = Omit<LemonDropdownProps, 'overlay' | 'trigger' | 'children'> & {
    time: string | dayjs.Dayjs
    showSeconds?: boolean
    formatDate?: string
    formatTime?: string
    showPopover?: boolean
    noStyles?: boolean
    className?: string
}

const TZLabelPopoverContent = React.memo(function TZLabelPopoverContent({
    showSeconds,
    time,
}: Pick<TZLabelProps, 'showSeconds'> & { time: dayjs.Dayjs }): JSX.Element {
    const DATE_OUTPUT_FORMAT = !showSeconds ? BASE_OUTPUT_FORMAT : `${BASE_OUTPUT_FORMAT}:ss`
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
                    <LemonButton icon={<IconSettings />} size="small" to={urls.projectSettings('timezone')} />
                </span>
            </div>

            <LemonDivider />

            <div className="space-y-2">
                <div className="TZLabelPopover__row">
                    <div>
                        <LaptopOutlined /> {shortTimeZone(undefined, time.toDate())}
                    </div>
                    <div>Your device</div>
                    <div>{time.format(DATE_OUTPUT_FORMAT)}</div>
                </div>
                {currentTeam && (
                    <div className="TZLabelPopover__row">
                        <div>
                            <ProjectOutlined /> {shortTimeZone(currentTeam.timezone, time.toDate())}
                        </div>
                        <div>Project</div>
                        <div>{time.tz(currentTeam.timezone).format(DATE_OUTPUT_FORMAT)}</div>
                    </div>
                )}
                {currentTeam?.timezone !== 'UTC' && (
                    <div className="TZLabelPopover__row">
                        <div>
                            <GlobalOutlined /> UTC
                        </div>
                        <div />
                        <div>{time.tz('UTC').format(DATE_OUTPUT_FORMAT)}</div>
                    </div>
                )}
            </div>
        </div>
    )
})

/** Return a simple label component with timezone conversion UI. */
function TZLabelRaw({
    time,
    showSeconds,
    formatDate,
    formatTime,
    showPopover = true,
    noStyles = false,
    className,
    ...dropdownProps
}: TZLabelProps): JSX.Element {
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

    const innerContent = (
        <span
            className={
                !noStyles ? clsx('whitespace-nowrap', showPopover && 'border-dotted border-b', className) : className
            }
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
}
// Timezone calculations are quite expensive, so the component is memoized to reduce them.
export const TZLabel = React.memo(TZLabelRaw) as typeof TZLabelRaw
