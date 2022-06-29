import React, { useState } from 'react'
import { Button } from 'antd'
import './DateFilterRangeExperiment.scss'
import { dayjs } from 'lib/dayjs'
import { DatePicker } from '../DatePicker'
import clsx from 'clsx'

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
    pickerRef?: React.MutableRefObject<any>
}): JSX.Element {
    const [calendarOpen, setCalendarOpen] = useState(true)

    return (
        <div>
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
                    pickerRef={props.pickerRef}
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
                                    ['date-filter-today']:
                                        current.date() === today.date() &&
                                        current.month() === today.month() &&
                                        current.year() === today.year(),
                                })}
                            >
                                {current.date()}
                            </div>
                        )
                    }}
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
