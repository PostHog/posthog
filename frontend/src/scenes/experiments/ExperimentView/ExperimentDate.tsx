import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonCalendarSelectInput } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useState } from 'react'

const ExperimentDate = ({
    label,
    date,
    onChange,
    selectionLimitDate,
    'data-attr': dataAttr,
}: {
    label: string
    date?: string | null
    selectionLimitDate?: string | null
    onChange?: (date: string) => void
    'data-attr'?: string
}): JSX.Element | null => {
    const [isDatePickerOpen, setIsDatePickerOpen] = useState(false)

    if (!date) {
        return null
    }

    return (
        <div className="block" data-attr={dataAttr}>
            <div className={clsx('text-xs font-semibold uppercase tracking-wide', isDatePickerOpen && 'text-center')}>
                {label}
            </div>
            <div className="flex">
                {isDatePickerOpen ? (
                    <LemonCalendarSelectInput
                        granularity="minute"
                        visible
                        value={dayjs(date)}
                        onChange={(newDate) => {
                            if (newDate && onChange) {
                                onChange(newDate.toISOString())
                            }
                        }}
                        onClose={() => setIsDatePickerOpen(false)}
                        onClickOutside={() => setIsDatePickerOpen(false)}
                        clearable={false}
                        selectionPeriod="past"
                        buttonProps={{ size: 'xsmall', 'data-attr': `${dataAttr}-picker` }}
                        selectionPeriodLimit={selectionLimitDate ? dayjs(selectionLimitDate) : undefined}
                    />
                ) : (
                    <>
                        <TZLabel time={date} />
                        <LemonButton
                            title={`Move ${label}`}
                            data-attr={`move-${dataAttr}`}
                            icon={<IconPencil />}
                            size="small"
                            onClick={() => setIsDatePickerOpen(true)}
                            noPadding
                            className="ml-2"
                        />
                    </>
                )}
            </div>
        </div>
    )
}

export default ExperimentDate
