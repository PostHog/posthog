import React from 'react'
import './index.scss'
import dayjs from 'dayjs'
import { Popover } from 'antd'
import relativeTime from 'dayjs/plugin/relativeTime'
import LocalizedFormat from 'dayjs/plugin/localizedFormat'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

dayjs.extend(LocalizedFormat)
dayjs.extend(relativeTime)
dayjs.extend(utc)
dayjs.extend(timezone)

/* TZLabel - Returns a simple label component with the timezone conversion elements */
export function TZLabel({ time }: { time: string | dayjs.Dayjs }): JSX.Element {
    const parsedTime = dayjs.isDayjs(time) ? time : dayjs(time)
    const { currentTeam } = useValues(teamLogic)

    const PopoverContent = (
        <div className="tz-label-popover">
            <h3 className="l3">Timezone conversion</h3>
            <div className="divider" />
            <div className="timezones">
                {currentTeam && (
                    <div className="timezone">
                        <div className="name">EST</div>
                        <div className="scope">| Project</div>
                        <div className="time">{parsedTime.tz(currentTeam.timezone).format('LLL')}</div>
                    </div>
                )}
                <div className="timezone">
                    <div className="name">EST</div>
                    <div className="scope">| Your computer</div>
                    <div className="time">{parsedTime.format('LLL')}</div>
                </div>
                <div className="timezone">
                    <div className="name">UTC</div>
                    <div className="scope" />
                    <div className="time">{parsedTime.tz('UTC').format('LLL')}</div>
                </div>
            </div>
        </div>
    )

    return (
        <Popover content={PopoverContent}>
            <span className="tz-label">{parsedTime.fromNow()}</span>
        </Popover>
    )
}
