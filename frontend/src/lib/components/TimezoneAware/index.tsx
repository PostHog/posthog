import React from 'react'
import './index.scss'
import dayjs from 'dayjs'
import { Col, Popover, Row } from 'antd'
import relativeTime from 'dayjs/plugin/relativeTime'
import LocalizedFormat from 'dayjs/plugin/localizedFormat'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { ProjectOutlined, LaptopOutlined, GlobalOutlined, SettingOutlined } from '@ant-design/icons'
import { Link } from '../Link'
import { shortTimeZone } from 'lib/utils'

const BASE_OUTPUT_FORMAT = 'ddd, MMM D, YYYY HH:mm'

dayjs.extend(LocalizedFormat)
dayjs.extend(relativeTime)
dayjs.extend(utc)
dayjs.extend(timezone)

/* TZLabel - Returns a simple label component with the timezone conversion elements */
export function TZLabel({ time, showSeconds }: { time: string | dayjs.Dayjs; showSeconds?: boolean }): JSX.Element {
    const parsedTime = dayjs.isDayjs(time) ? time : dayjs(time)
    const { currentTeam } = useValues(teamLogic)

    const DATE_OUTPUT_FORMAT = !showSeconds ? BASE_OUTPUT_FORMAT : `${BASE_OUTPUT_FORMAT}:ss`
    const timeStyle = showSeconds ? { minWidth: 192 } : undefined

    const PopoverContent = (
        <div className="tz-label-popover">
            <h3 className="l3">
                Timezone conversion
                <span className="float-right">
                    <Link to="/project/settings#timezone">
                        <SettingOutlined />
                    </Link>
                </span>
            </h3>
            <div className="divider" />
            <div className="timezones">
                {currentTeam && (
                    <Row className="timezone">
                        <Col className="name">
                            <ProjectOutlined /> {shortTimeZone(currentTeam.timezone, parsedTime.toDate())}
                        </Col>
                        <Col className="scope">| Project</Col>
                        <Col className="time" style={timeStyle}>
                            {parsedTime.tz(currentTeam.timezone).format(DATE_OUTPUT_FORMAT)}
                        </Col>
                    </Row>
                )}
                <Row className="timezone">
                    <Col className="name">
                        <LaptopOutlined /> {shortTimeZone(undefined, parsedTime.toDate())}
                    </Col>
                    <Col className="scope">| Your computer</Col>
                    <Col className="time" style={timeStyle}>
                        {parsedTime.format(DATE_OUTPUT_FORMAT)}
                    </Col>
                </Row>
                <Row className="timezone">
                    <Col className="name">
                        <GlobalOutlined /> UTC
                    </Col>
                    <Col className="scope" />
                    <Col className="time" style={timeStyle}>
                        {parsedTime.tz('UTC').format(DATE_OUTPUT_FORMAT)}
                    </Col>
                </Row>
            </div>
        </div>
    )

    return (
        <Popover content={PopoverContent}>
            <span className="tz-label">{parsedTime.fromNow()}</span>
        </Popover>
    )
}
