import './index.scss'
import { Col, Popover, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { ProjectOutlined, LaptopOutlined, GlobalOutlined, SettingOutlined } from '@ant-design/icons'
import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyDetailedTime, shortTimeZone } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from '../../../scenes/teamLogic'
import { dayjs } from 'lib/dayjs'
import clsx from 'clsx'
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { styles } from '../../../styles/vars'

const BASE_OUTPUT_FORMAT = 'ddd, MMM D, YYYY h:mm A'

function TZConversionHeader(): JSX.Element {
    return (
        <h3 className="l3">
            Timezone conversion
            <span className="float-right">
                <Link to="/project/settings#timezone">
                    <SettingOutlined />
                </Link>
            </span>
        </h3>
    )
}

interface TZLabelRawProps {
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
}: Pick<TZLabelRawProps, 'showSeconds'> & { time: dayjs.Dayjs }): JSX.Element {
    const DATE_OUTPUT_FORMAT = !showSeconds ? BASE_OUTPUT_FORMAT : `${BASE_OUTPUT_FORMAT}:ss`
    const timeStyle = showSeconds ? { minWidth: 192 } : undefined
    const { currentTeam } = useValues(teamLogic)
    const { reportTimezoneComponentViewed } = useActions(eventUsageLogic)

    useEffect(() => {
        reportTimezoneComponentViewed('label', currentTeam?.timezone, shortTimeZone())
    }, [])

    return (
        <div className="tz-label-popover">
            <TZConversionHeader />
            <div className="divider" />
            <div className="timezones">
                <Row className="timezone">
                    <Col className="name">
                        <LaptopOutlined /> {shortTimeZone(undefined, time.toDate())}
                    </Col>
                    <Col className="scope">Your device</Col>
                    <Col className="time" style={timeStyle}>
                        {time.format(DATE_OUTPUT_FORMAT)}
                    </Col>
                </Row>
                {currentTeam && (
                    <Row className="timezone">
                        <Col className="name">
                            <ProjectOutlined /> {shortTimeZone(currentTeam.timezone, time.toDate())}
                        </Col>
                        <Col className="scope">Project</Col>
                        <Col className="time" style={timeStyle}>
                            {time.tz(currentTeam.timezone).format(DATE_OUTPUT_FORMAT)}
                        </Col>
                    </Row>
                )}
                {currentTeam?.timezone !== 'UTC' && (
                    <Row className="timezone">
                        <Col className="name">
                            <GlobalOutlined /> UTC
                        </Col>
                        <Col className="scope" />
                        <Col className="time" style={timeStyle}>
                            {time.tz('UTC').format(DATE_OUTPUT_FORMAT)}
                        </Col>
                    </Row>
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
}: TZLabelRawProps): JSX.Element {
    // usePeriodicRerender(1000)

    const parsedTime = useMemo(() => (dayjs.isDayjs(time) ? time : dayjs(time)), [time])

    const format = useCallback(() => {
        return formatDate || formatTime
            ? humanFriendlyDetailedTime(parsedTime, formatDate, formatTime)
            : parsedTime.fromNow()
    }, [formatDate, formatTime, parsedTime])

    const [formattedContent, setFormattedContent] = useState(format())

    useEffect(() => {
        const interval = setInterval(() => {
            if (format() !== formattedContent) {
                setFormattedContent(format())
            }
        }, 1000)
        return () => clearInterval(interval)
    }, [parsedTime])

    const innerContent = (
        <span className={!noStyles ? clsx('tz-label', showPopover && 'tz-label--hoverable', className) : className}>
            {formattedContent}
        </span>
    )

    if (showPopover) {
        return (
            <Popover
                content={<TZLabelPopoverContent time={parsedTime} showSeconds={showSeconds} />}
                zIndex={styles.zPopover}
            >
                {innerContent}
            </Popover>
        )
    }

    return innerContent
}
// Timezone calculations are quite expensive, so the component is memoized to reduce them.
export const TZLabel = React.memo(TZLabelRaw) as typeof TZLabelRaw
