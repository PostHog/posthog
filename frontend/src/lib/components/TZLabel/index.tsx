import './index.scss'
import { Col, Popover, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { ProjectOutlined, LaptopOutlined, GlobalOutlined, SettingOutlined } from '@ant-design/icons'
import { Link } from '../Link'
import { humanFriendlyDetailedTime, shortTimeZone } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from '../../../scenes/teamLogic'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import clsx from 'clsx'
import React from 'react'
import { styles } from '../../../styles/vars'

const BASE_OUTPUT_FORMAT = 'ddd, MMM D, YYYY HH:mm'

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
    usePeriodicRerender(1000)

    const parsedTime = dayjs.isDayjs(time) ? time : dayjs(time)
    const { currentTeam } = useValues(teamLogic)

    const DATE_OUTPUT_FORMAT = !showSeconds ? BASE_OUTPUT_FORMAT : `${BASE_OUTPUT_FORMAT}:ss`
    const timeStyle = showSeconds ? { minWidth: 192 } : undefined

    const { reportTimezoneComponentViewed } = useActions(eventUsageLogic)

    const innerContent = (
        <span className={!noStyles ? clsx('tz-label', showPopover && 'tz-label--hoverable', className) : className}>
            {formatDate || formatTime
                ? humanFriendlyDetailedTime(parsedTime, formatDate, formatTime)
                : parsedTime.fromNow()}
        </span>
    )

    if (showPopover) {
        const handleVisibleChange = (visible: boolean): void => {
            if (visible) {
                reportTimezoneComponentViewed('label', currentTeam?.timezone, shortTimeZone())
            }
        }

        const PopoverContent = (
            <div className="tz-label-popover">
                <TZConversionHeader />
                <div className="divider" />
                <div className="timezones">
                    <Row className="timezone">
                        <Col className="name">
                            <LaptopOutlined /> {shortTimeZone(undefined, parsedTime.toDate())}
                        </Col>
                        <Col className="scope">Your device</Col>
                        <Col className="time" style={timeStyle}>
                            {parsedTime.format(DATE_OUTPUT_FORMAT)}
                        </Col>
                    </Row>
                    {currentTeam && (
                        <Row className="timezone">
                            <Col className="name">
                                <ProjectOutlined /> {shortTimeZone(currentTeam.timezone, parsedTime.toDate())}
                            </Col>
                            <Col className="scope">Project</Col>
                            <Col className="time" style={timeStyle}>
                                {parsedTime.tz(currentTeam.timezone).format(DATE_OUTPUT_FORMAT)}
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
                                {parsedTime.tz('UTC').format(DATE_OUTPUT_FORMAT)}
                            </Col>
                        </Row>
                    )}
                </div>
            </div>
        )

        return (
            <Popover content={PopoverContent} onVisibleChange={handleVisibleChange} zIndex={styles.zPopup}>
                {innerContent}
            </Popover>
        )
    }

    return innerContent
}
// Timezone calculations are quite expensive, so the component is memoized to reduce them.
export const TZLabel = React.memo(TZLabelRaw) as typeof TZLabelRaw
