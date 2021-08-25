import React, { useMemo, useState } from 'react'
import { Select } from 'antd'
import dayjs from 'dayjs'
import { dateMapping, isDate, dateFilterToText } from 'lib/utils'
import { DateFilterRange } from 'lib/components/DateFilter/DateFilterRange'

export interface DateFilterProps {
    defaultValue: string
    showCustom?: boolean
    bordered?: boolean
    makeLabel?: (key: string) => React.ReactNode
    style?: React.CSSProperties
    onChange?: (fromDate: string, toDate: string) => void
    disabled?: boolean
    getPopupContainer?: (props: any) => HTMLElement
}

interface RawDateFilterProps extends DateFilterProps {
    dateFrom?: string | dayjs.Dayjs
    dateTo?: string | dayjs.Dayjs
}

export function DateFilter({
    bordered,
    defaultValue,
    showCustom,
    style,
    disabled,
    makeLabel,
    onChange,
    getPopupContainer,
    dateFrom,
    dateTo,
}: RawDateFilterProps): JSX.Element {
    const [rangeDateFrom, setRangeDateFrom] = useState(
        dateFrom && isDate.test(dateFrom as string) ? dayjs(dateFrom) : undefined
    )
    const [rangeDateTo, setRangeDateTo] = useState(dateTo && isDate.test(dateTo as string) ? dayjs(dateTo) : undefined)
    const [dateRangeOpen, setDateRangeOpen] = useState(false)
    const [open, setOpen] = useState(false)

    function onClickOutside(): void {
        setOpen(false)
        setDateRangeOpen(false)
    }

    function setDate(fromDate: string, toDate: string): void {
        onChange?.(fromDate, toDate)
    }

    function _onChange(v: string): void {
        if (v === 'Date range') {
            if (open) {
                setOpen(false)
                setDateRangeOpen(true)
            }
        } else {
            setDate(dateMapping[v].values[0], dateMapping[v].values[1])
        }
    }

    function onBlur(): void {
        if (dateRangeOpen) {
            return
        }
        onClickOutside()
    }

    function onClick(): void {
        if (dateRangeOpen) {
            return
        }
        setOpen(!open)
    }

    function dropdownOnClick(e: React.MouseEvent): void {
        e.preventDefault()
        setOpen(true)
        setDateRangeOpen(false)
        document.getElementById('daterange_selector')?.focus()
    }

    function onApplyClick(): void {
        onClickOutside()
        setDate(dayjs(rangeDateFrom).format('YYYY-MM-DD'), dayjs(rangeDateTo).format('YYYY-MM-DD'))
    }

    const parsedValue = useMemo(() => dateFilterToText(dateFrom, dateTo, defaultValue), [
        dateFrom,
        dateTo,
        defaultValue,
    ])

    return (
        <Select
            data-attr="date-filter"
            bordered={bordered}
            id="daterange_selector"
            value={parsedValue}
            onChange={_onChange}
            style={{
                marginRight: 4,
                ...style,
            }}
            open={open || dateRangeOpen}
            onBlur={onBlur}
            onClick={onClick}
            listHeight={440}
            dropdownMatchSelectWidth={false}
            disabled={disabled}
            optionLabelProp={makeLabel ? 'label' : undefined}
            getPopupContainer={getPopupContainer}
            dropdownRender={(menu: React.ReactElement) => {
                if (dateRangeOpen) {
                    return (
                        <DateFilterRange
                            getPopupContainer={getPopupContainer}
                            onClick={dropdownOnClick}
                            onDateFromChange={(date) => setRangeDateFrom(date)}
                            onDateToChange={(date) => setRangeDateTo(date)}
                            onApplyClick={onApplyClick}
                            onClickOutside={onClickOutside}
                            rangeDateFrom={rangeDateFrom}
                            rangeDateTo={rangeDateTo}
                        />
                    )
                } else {
                    return menu
                }
            }}
        >
            {[
                ...Object.entries(dateMapping).map(([key, { inactive }]) => {
                    if (key === 'Custom' && !showCustom) {
                        return null
                    }

                    if (inactive && parsedValue !== key) {
                        return null
                    }

                    return (
                        <Select.Option key={key} value={key} label={makeLabel ? makeLabel(key) : undefined}>
                            {key}
                        </Select.Option>
                    )
                }),

                <Select.Option key={'Date range'} value={'Date range'}>
                    {'Date range'}
                </Select.Option>,
            ]}
        </Select>
    )
}
