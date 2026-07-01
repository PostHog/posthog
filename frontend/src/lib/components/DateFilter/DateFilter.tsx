import { useValues } from 'kea'
import { ComponentPropsWithoutRef, forwardRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs, isDayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { LemonDatePicker } from './LemonDatePicker'
import { QuillDateFilter } from './QuillDateFilter'

export type { LemonDatePickerProps } from './LemonDatePicker'

export interface DateFilterProps extends ComponentPropsWithoutRef<typeof LemonDatePicker> {
    /** `data-attr` for the Quill variant's trigger button. */
    dataAttr?: string
}

function toDateString(date: string | null | dayjs.Dayjs | undefined): string | null {
    if (date == null) {
        return null
    }
    return isDayjs(date) ? date.toISOString() : date
}

/**
 * The date filter used across the app. Reads the `DATEPICKER_COMPONENT`
 * multivariate flag and renders either the LemonUI `LemonDatePicker` (control /
 * unset — the default everywhere today) or the Quill `QuillDateFilter` (quill).
 *
 * Same props as `LemonDatePicker`, so it's a drop-in. The Quill variant only
 * understands the shared `dateFrom`/`dateTo`/`onChange` contract, so the
 * LemonUI-only options (and the forwarded ref) are ignored when it is active.
 */
export const DateFilter = forwardRef<HTMLButtonElement, DateFilterProps>(function DateFilter(
    { dataAttr, ...props },
    ref
) {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.DATEPICKER_COMPONENT] === 'quill') {
        return (
            <QuillDateFilter
                dateFrom={toDateString(props.dateFrom)}
                dateTo={toDateString(props.dateTo)}
                onChange={(dateFrom, dateTo) => props.onChange?.(dateFrom, dateTo)}
                dataAttr={dataAttr}
            />
        )
    }

    return <LemonDatePicker ref={ref} {...props} />
})
