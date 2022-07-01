import React, { useRef, useMemo, useState } from 'react'
import { Select } from 'antd'
import { SelectProps } from 'antd/lib/select'
import { dateMapping, dateMappingExperiment, isDate, dateFilterToText } from 'lib/utils'
import { DateFilterRange } from 'lib/components/DateFilter/DateFilterRange'
import { DateFilterRangeExperiment } from 'lib/components/DateFilter/DateFilterRangeExperiment'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dateMappingOption } from '~/types'
import { dayjs } from 'lib/dayjs'
import './DateFilterExperiment.scss'
import { Tooltip } from 'lib/components/Tooltip'
import { dateFilterLogic } from './dateFilterLogic'
import { RollingDateRangeFilter } from './RollingDateRangeFilter'
import { useActions, useValues } from 'kea'
import { LemonButtonWithPopup, LemonDivider, LemonButton } from '@posthog/lemon-ui'
import { CalendarOutlined } from '@ant-design/icons'
import { FEATURE_FLAGS } from 'lib/constants'

export interface DateFilterProps {
    defaultValue: string
    showCustom?: boolean
    bordered?: boolean // remove if experiment is successful
    showRollingRangePicker?: boolean // experimental
    makeLabel?: (key: React.ReactNode) => React.ReactNode
    style?: React.CSSProperties
    popupStyle?: React.CSSProperties // experimental
    onChange?: (fromDate: string, toDate: string) => void
    disabled?: boolean
    getPopupContainer?: (props: any) => HTMLElement
    dateOptions?: dateMappingOption[]
    isDateFormatted?: boolean
    selectProps?: SelectProps<any> // remove if experiment is successful
}
interface RawDateFilterProps extends DateFilterProps {
    dateFrom?: string | null | dayjs.Dayjs
    dateTo?: string | null | dayjs.Dayjs
}

function _DateFilter({
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
    dateOptions = dateMapping,
    isDateFormatted = false,
    selectProps = {},
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
            const option = dateOptions.find((option) => !option.inactive && option.key === v)
            if (option) {
                setDate(option.values[0], option.values[1])
            }
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

    const currKey = useMemo(
        () => dateFilterToText(dateFrom, dateTo, defaultValue, dateOptions, false),
        [dateFrom, dateTo, defaultValue]
    )

    return (
        <Select
            data-attr="date-filter"
            bordered={bordered}
            id="daterange_selector"
            value={
                isDateFormatted && !dateOptions.find((option) => option.key === currKey)
                    ? dateFilterToText(dateFrom, dateTo, defaultValue, dateOptions, true)
                    : currKey
            }
            onChange={_onChange}
            style={style}
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
                            disableBeforeYear={2015}
                        />
                    )
                } else {
                    return menu
                }
            }}
            {...selectProps}
        >
            {[
                ...dateOptions.map(({ key, values, inactive }) => {
                    if (key === 'Custom' && !showCustom) {
                        return null
                    }

                    if (inactive && currKey !== key) {
                        return null
                    }

                    const dateValue = dateFilterToText(values[0], values[1], defaultValue, dateOptions, isDateFormatted)

                    return (
                        <Select.Option key={key} value={key} label={makeLabel ? makeLabel(dateValue) : undefined}>
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

function DateFilterExperiment({
    defaultValue,
    showCustom,
    showRollingRangePicker = true,
    style,
    popupStyle,
    disabled,
    makeLabel,
    onChange,
    getPopupContainer,
    dateFrom,
    dateTo,
    dateOptions = dateMappingExperiment,
    isDateFormatted = true,
}: RawDateFilterProps): JSX.Element {
    const logicProps = { dateFrom, dateTo, onChange, defaultValue, dateOptions, isDateFormatted }
    const { open, openDateRange, close, setRangeDateFrom, setRangeDateTo, setDate } = useActions(
        dateFilterLogic(logicProps)
    )
    const { isOpen, isDateRangeOpen, rangeDateFrom, rangeDateTo, value, isFixedDateRange, isRollingDateRange } =
        useValues(dateFilterLogic(logicProps))

    const optionsRef = useRef<HTMLDivElement | null>(null)
    const rollingDateRangeRef = useRef<HTMLDivElement | null>(null)

    function dropdownOnClick(e: React.MouseEvent): void {
        e.preventDefault()
        open()
        document.getElementById('daterange_selector')?.focus()
    }

    function onApplyClick(): void {
        close()
        const formattedRangeDateFrom = dayjs(rangeDateFrom).format('YYYY-MM-DD')
        const formattedRangeDateTo = dayjs(rangeDateTo).format('YYYY-MM-DD')
        setDate(formattedRangeDateFrom, formattedRangeDateTo)
    }

    const popupOverlay = isDateRangeOpen ? (
        <DateFilterRangeExperiment
            getPopupContainer={getPopupContainer}
            onClick={dropdownOnClick}
            onDateFromChange={(date) => setRangeDateFrom(date)}
            onDateToChange={(date) => setRangeDateTo(date)}
            onApplyClick={onApplyClick}
            onClickOutside={close}
            rangeDateFrom={rangeDateFrom}
            rangeDateTo={rangeDateTo}
            disableBeforeYear={2015}
        />
    ) : (
        <div ref={optionsRef} className="date-filter-options" onClick={(e) => e.stopPropagation()}>
            {[
                ...dateOptions.map(({ key, values, inactive }) => {
                    if (key === 'Custom' && !showCustom) {
                        return null
                    }

                    if (inactive && value !== key) {
                        return null
                    }

                    const isHighlighted = dateFrom === values[0] && dateTo === values[1]
                    const dateValue = dateFilterToText(values[0], values[1], defaultValue, dateOptions, isDateFormatted)

                    return (
                        <Tooltip key={key} title={makeLabel ? makeLabel(dateValue) : undefined}>
                            <LemonButton
                                key={key}
                                onClick={() => {
                                    setDate(values[0], values[1])
                                    close()
                                }}
                                type={isHighlighted ? 'highlighted' : 'stealth'}
                                fullWidth
                            >
                                {key}
                            </LemonButton>
                        </Tooltip>
                    )
                }),
            ]}
            {showRollingRangePicker && (
                <RollingDateRangeFilter
                    dateFrom={dateFrom}
                    selected={isRollingDateRange}
                    onChange={(fromDate) => {
                        setDate(fromDate, '')
                        close()
                    }}
                    makeLabel={makeLabel}
                    popupRef={rollingDateRangeRef}
                />
            )}
            <LemonDivider />
            <LemonButton onClick={openDateRange} type={isFixedDateRange ? 'highlighted' : 'stealth'} fullWidth>
                {'Custom fixed time period'}
            </LemonButton>
        </div>
    )

    return (
        <LemonButtonWithPopup
            data-attr="date-filter"
            id="daterange_selector"
            onClick={isOpen ? close : open}
            value={value}
            disabled={disabled}
            style={{ ...style, border: '1px solid var(--border)' }} //TODO this is a css hack, so that this button aligns with others on the page which are still on antd
            size={'small'}
            type={'stealth'}
            popup={{
                onClickOutside: close,
                visible: isOpen || isDateRangeOpen,
                overlay: popupOverlay,
                placement: 'bottom-start',
                actionable: true,
                closeOnClickInside: false,
                additionalRefs: [rollingDateRangeRef, '.datefilter-datepicker'],
                style: popupStyle,
            }}
            icon={<CalendarOutlined />}
        >
            {value}
        </LemonButtonWithPopup>
    )
}

export function DateFilter(props: RawDateFilterProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const experimentEnabled = featureFlags[FEATURE_FLAGS.DATE_FILTER_EXPERIMENT] === 'test'
    return experimentEnabled ? <DateFilterExperiment {...props} /> : <_DateFilter {...props} />
}
