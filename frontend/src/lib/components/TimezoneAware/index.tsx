import React from 'react'
import './index.scss'
import { Col, Popover, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { ProjectOutlined, LaptopOutlined, GlobalOutlined, SettingOutlined } from '@ant-design/icons'
import { Link } from '../Link'
import { humanFriendlyDetailedTime, humanTzOffset, shortTimeZone } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { teamLogic } from '../../../scenes/teamLogic'
import { dayjs } from 'lib/dayjs'

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

/** Return a simple label component with timezone conversion UI. */
function TZLabelRaw({
    time,
    showSeconds,
    formatString,
}: {
    time: string | dayjs.Dayjs
    showSeconds?: boolean
    formatString?: string
}): JSX.Element {
    const parsedTime = dayjs.isDayjs(time) ? time : dayjs(time)
    const { currentTeam } = useValues(teamLogic)

    const DATE_OUTPUT_FORMAT = !showSeconds ? BASE_OUTPUT_FORMAT : `${BASE_OUTPUT_FORMAT}:ss`
    const timeStyle = showSeconds ? { minWidth: 192 } : undefined

    const { reportTimezoneComponentViewed } = useActions(eventUsageLogic)

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
        <Popover content={PopoverContent} onVisibleChange={handleVisibleChange}>
            <span className="tz-label">
                {formatString ? humanFriendlyDetailedTime(parsedTime, undefined, formatString) : parsedTime.fromNow()}
            </span>
        </Popover>
    )
}
// Timezone calculations are quite expensive, so the component is memoized to reduce them.
export const TZLabel = React.memo(TZLabelRaw) as typeof TZLabelRaw

/** Return an explainer component for analytics visualization pages. */
function TZIndicatorRaw({
    style,
    placement,
}: {
    style?: React.CSSProperties
    placement?: TooltipPlacement
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const { reportTimezoneComponentViewed } = useActions(eventUsageLogic)

    const handleVisibleChange = (visible: boolean): void => {
        if (visible) {
            reportTimezoneComponentViewed('indicator', currentTeam?.timezone, shortTimeZone())
        }
    }

    const PopoverContent = (
        <div className="tz-label-popover">
            <TZConversionHeader />
            <p style={{ maxWidth: 320 }}>
                All graphs are calculated and presented in UTC (GMT timezone).
                <br />
                Conversion to your local timezones are shown below.
            </p>
            <div className="divider" />
            <div className="timezones">
                <Row className="timezone">
                    <Col className="name">
                        <LaptopOutlined /> {shortTimeZone(undefined)}
                    </Col>
                    <Col className="scope">Your device</Col>
                    <Col className="time" style={{ minWidth: 100, fontWeight: 'bold' }}>
                        {humanTzOffset()}
                    </Col>
                </Row>
                {currentTeam && (
                    <Row className="timezone">
                        <Col className="name">
                            <ProjectOutlined /> {shortTimeZone(currentTeam.timezone)}
                        </Col>
                        <Col className="scope">Project</Col>
                        <Col className="time" style={{ minWidth: 100, fontWeight: 'bold' }}>
                            {humanTzOffset(currentTeam.timezone)}
                        </Col>
                    </Row>
                )}
            </div>
        </div>
    )

    return (
        <Popover content={PopoverContent} onVisibleChange={handleVisibleChange} placement={placement}>
            <span className="tz-indicator" style={style}>
                <GlobalOutlined /> UTC
            </span>
        </Popover>
    )
}
// Timezone calculations are quite expensive, so the component is memoized to reduce them.
export const TZIndicator = React.memo(TZIndicatorRaw) as typeof TZIndicatorRaw
