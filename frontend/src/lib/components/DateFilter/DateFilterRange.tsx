import React, { useState, useRef } from 'react'
import { Button } from 'antd'
import './DateFilterRange.scss'
import { dayjs } from 'lib/dayjs'
import { DatePicker } from '../DatePicker'
import clsx from 'clsx'
import { useOutsideClickHandler } from 'lib/hooks/useOutsideClickHandler'
import { RightOutlined, LeftOutlined, DoubleRightOutlined, DoubleLeftOutlined } from '@ant-design/icons'
import { Tooltip } from '../Tooltip'

export function DateFilterRange(props: {
    onClickOutside: () => void
    onClick: (e: React.MouseEvent) => void
    onDateFromChange: (date?: dayjs.Dayjs) => void
    onDateToChange: (date?: dayjs.Dayjs) => void
    onApplyClick: () => void
    rangeDateFrom?: string | dayjs.Dayjs | null
    rangeDateTo?: string | dayjs.Dayjs | null
    getPopupContainer?: (props: any) => HTMLElement
    disableBeforeYear?: number
}): JSX.Element {
    const dropdownRef = useRef<HTMLDivElement | null>(null)
    const [calendarOpen, setCalendarOpen] = useState(true)

    useOutsideClickHandler(
        '.datefilter-datepicker',
        () => {
            if (calendarOpen) {
                setCalendarOpen(false)
            }
        },
        [calendarOpen],
        ['INPUT']
    )

    return (
        <div ref={dropdownRef}>
            <a
                style={{
                    margin: '0 1rem',
                    color: 'rgba(0, 0, 0, 0.2)',
                    fontWeight: 700,
                }}
                href="#"
                onClick={props.onClick}
            >
                &lt;
            </a>
            <hr style={{ margin: '0.5rem 0' }} />
            <div style={{ padding: '0 1rem' }}>
                <label className="secondary">From date</label>
                <br />
                <DatePicker.RangePicker
                    dropdownClassName="datefilter-datepicker"
                    getPopupContainer={props.getPopupContainer}
                    defaultValue={[
                        props.rangeDateFrom
                            ? dayjs.isDayjs(props.rangeDateFrom)
                                ? props.rangeDateFrom
                                : dayjs(props.rangeDateFrom)
                            : null,
                        props.rangeDateTo
                            ? dayjs.isDayjs(props.rangeDateTo)
                                ? props.rangeDateTo
                                : dayjs(props.rangeDateTo)
                            : null,
                    ]}
                    open={calendarOpen}
                    onOpenChange={(open) => {
                        if (open) {
                            setCalendarOpen(open)
                        }
                    }}
                    onChange={(dates) => {
                        if (dates && dates.length === 2) {
                            props.onDateFromChange(dates[0] || undefined)
                            props.onDateToChange(dates[1] || undefined)
                            setCalendarOpen(false)
                        }
                    }}
                    popupStyle={{ zIndex: 999999 }}
                    disabledDate={(date) =>
                        (!!props.disableBeforeYear && date.year() < props.disableBeforeYear) || date.isAfter(dayjs())
                    }
                    dateRender={(current, today) => {
                        return (
                            <div
                                className={clsx('ant-picker-cell-inner', {
                                    ['DateFilterRange__calendartoday']:
                                        current.date() === today.date() &&
                                        current.month() === today.month() &&
                                        current.year() === today.year(),
                                })}
                            >
                                {current.date()}
                            </div>
                        )
                    }}
                    nextIcon={
                        <Tooltip title="Next month">
                            <RightOutlined />
                        </Tooltip>
                    }
                    superNextIcon={
                        <Tooltip title="Next year">
                            <DoubleRightOutlined />
                        </Tooltip>
                    }
                    prevIcon={
                        <Tooltip title="Previous month">
                            <LeftOutlined />
                        </Tooltip>
                    }
                    superPrevIcon={
                        <Tooltip title="Previous year">
                            <DoubleLeftOutlined />
                        </Tooltip>
                    }
                />
                <br />
                <Button
                    type="default"
                    disabled={!props.rangeDateTo || !props.rangeDateFrom}
                    style={{ marginTop: '1rem', marginBottom: '1rem' }}
                    onClick={props.onApplyClick}
                >
                    Apply filter
                </Button>
            </div>
        </div>
    )
}
