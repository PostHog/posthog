import React from 'react'
import './index.scss'
import dayjs from 'dayjs'

/* TZLabel - Returns a simple label component with the timezone conversion elements */
export function TZLabel({ time }: { time: string | dayjs.Dayjs }): JSX.Element {
    const parsedTime = dayjs.isDayjs(time) ? time : dayjs(time)
    return <span className="tz-label">{parsedTime}</span>
}
