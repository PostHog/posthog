import './index.scss'

// eslint-disable-next-line no-restricted-imports
import { LaptopOutlined, ProjectOutlined } from '@ant-design/icons'
import { IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonDropdownProps } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { IconWeb } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime, shortTimeZone } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { urls } from 'scenes/urls'

import { teamLogic } from '../../../scenes/teamLogic'

const BASE_OUTPUT_FORMAT = 'ddd, MMM D, YYYY h:mm A'
const BASE_OUTPUT_FORMAT_WITH_SECONDS = 'ddd, MMM D, YYYY h:mm:ss A'

export type TZLabelProps = Omit<LemonDropdownProps, 'overlay' | 'trigger' | 'children'> & {
    /** The time to be rendered */
    time: string | dayjs.Dayjs
    /** Render as an absolute time instead of the default relative time  @default false*/
    absolute?: boolean

    /** Whether to show seconds in the popover content  */
    hidePopover?: boolean
    /** Whether to show seconds in the popover content  */
    showSecondsInPopover?: boolean

    // formatDate?: string
    // formatTime?: string
    className?: string
}

const TZLabelPopoverContent = React.memo(function TZLabelPopoverContent({
    showSecondsInPopover,
    time,
}: Pick<TZLabelProps, 'showSecondsInPopover'> & { time: dayjs.Dayjs }): JSX.Element {
    const DATE_OUTPUT_FORMAT = !showSecondsInPopover ? BASE_OUTPUT_FORMAT : BASE_OUTPUT_FORMAT_WITH_SECONDS
    const { currentTeam } = useValues(teamLogic)
    const { reportTimezoneComponentViewed } = useActions(eventUsageLogic)

    useEffect(() => {
        reportTimezoneComponentViewed('label', currentTeam?.timezone, shortTimeZone())
    }, [])

    return (
        <div className={clsx('TZLabelPopover', showSecondsInPopover && 'TZLabelPopover--seconds')}>
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
                            <IconWeb /> UTC
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
    showSecondsInPopover: showSeconds,
    absolute = false,
    // formatDate,
    // formatTime,
    hidePopover = true,
    className,
    ...dropdownProps
}: TZLabelProps): JSX.Element {
    const parsedTime = useMemo(() => (dayjs.isDayjs(time) ? time : dayjs(time)), [time])

    const formatDate = absolute ? 'ddd, MMM D, YYYY' : undefined
    const formatTime = absolute ? 'h:mm A' : undefined

    const format = useCallback(() => {
        return formatDate || formatTime
            ? humanFriendlyDetailedTime(parsedTime, formatDate, formatTime)
            : parsedTime.fromNow()
    }, [formatDate, formatTime, parsedTime])

    const [formattedContent, setFormattedContent] = useState(format())

    useEffect(() => {
        const diff = Math.abs(dayjs().diff(parsedTime, 'seconds'))
        const intervalTime = diff < 60 ? 1000 : 60000

        // NOTE: This is an optimization to make sure we don't needlessly re-render the component every second.
        const interval = setInterval(() => {
            if (format() !== formattedContent) {
                setFormattedContent(format())
            }
        }, intervalTime)
        console.log('TZLabelRaw -> interval', intervalTime, diff)
        return () => clearInterval(interval)
    }, [parsedTime, format, formattedContent])

    const innerContent = (
        <span className={clsx('whitespace-nowrap align-middle', !hidePopover && 'border-dotted border-b', className)}>
            {formattedContent}
        </span>
    )

    if (!hidePopover) {
        return (
            <LemonDropdown
                placement="top"
                showArrow
                {...dropdownProps}
                trigger="hover"
                overlay={<TZLabelPopoverContent time={parsedTime} showSecondsInPopover={showSeconds} />}
            >
                {innerContent}
            </LemonDropdown>
        )
    }

    return innerContent
}
// Timezone calculations are quite expensive, so the component is memoized to reduce them.
export const TZLabel = React.memo(TZLabelRaw) as typeof TZLabelRaw
