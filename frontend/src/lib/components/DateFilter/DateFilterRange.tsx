import React, { useEffect, useRef, useState } from 'react'
import { Button } from 'antd'

import dayjsGenerateConfig from 'rc-picker/lib/generate/dayjs'
import generatePicker from 'antd/lib/date-picker/generatePicker'
import { dayjs } from 'lib/dayjs'

const DatePicker = generatePicker<dayjs.Dayjs>(dayjsGenerateConfig)

export function DateFilterRange(props: {
    onClickOutside: () => void
    onClick: (e: React.MouseEvent) => void
    onDateFromChange: (date?: dayjs.Dayjs) => void
    onDateToChange: (date?: dayjs.Dayjs) => void
    onApplyClick: () => void
    rangeDateFrom?: string | dayjs.Dayjs
    rangeDateTo?: string | dayjs.Dayjs
    getPopupContainer?: (props: any) => HTMLElement
}): JSX.Element {
    const dropdownRef = useRef<HTMLDivElement | null>(null)
    const [calendarOpen, setCalendarOpen] = useState(false)

    const onClickOutside = (event: MouseEvent): void => {
        const target = (event.composedPath?.()?.[0] || event.target) as HTMLElement

        if (!target) {
            return
        }

        const clickInPickerContainer = dropdownRef.current?.contains(target)
        const clickInDateDropdown = event
            .composedPath?.()
            ?.find((e) => (e as HTMLElement)?.matches?.('.datefilter-datepicker'))

        if (clickInPickerContainer && calendarOpen && target.tagName !== 'INPUT') {
            setCalendarOpen(false)
            return
        }

        if (!clickInPickerContainer && !clickInDateDropdown) {
            if (calendarOpen) {
                setCalendarOpen(false)
            } else {
                props.onClickOutside()
            }
        }
    }

    useEffect(() => {
        window.addEventListener('mousedown', onClickOutside)
        return () => {
            window.removeEventListener('mousedown', onClickOutside)
        }
    }, [calendarOpen])

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
