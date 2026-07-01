import { useValues } from 'kea'
import { ComponentPropsWithoutRef, forwardRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs, isDayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { LemonDatePicker } from './LemonDatePicker'
import { QuillDateFilter } from './QuillDateFilter'

export type { LemonDatePickerProps } from './LemonDatePicker'

export type DateFilterProps = ComponentPropsWithoutRef<typeof LemonDatePicker>

// The only props `QuillDateFilter` can honor. Any other prop (or a forwarded
// ref) is silently dropped by the Quill path, so when a caller passes one we
// must render `LemonDatePicker` even under the `quill` flag — otherwise flipping
// the flag would regress single-date mode, disabled states, custom `dateOptions`
// etc. for that caller with no type error.
const QUILL_SUPPORTED_PROPS = new Set<keyof DateFilterProps>(['dateFrom', 'dateTo', 'onChange', 'dataAttr'])

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
 * Same props as `LemonDatePicker`, so it's a drop-in. `QuillDateFilter` only
 * understands the shared `dateFrom`/`dateTo`/`onChange`/`dataAttr` contract, so
 * the entrypoint falls back to `LemonDatePicker` whenever a caller passes any
 * LemonUI-only prop (or a ref) even if the flag is `quill`. This keeps the flag
 * safe to flip globally: only surfaces that need nothing beyond a range are
 * actually swapped.
 */
export const DateFilter = forwardRef<HTMLButtonElement, DateFilterProps>(function DateFilter(
    { dataAttr, ...props },
    ref
) {
    const { featureFlags } = useValues(featureFlagLogic)

    const quillCanRender =
        ref == null &&
        Object.entries(props).every(
            ([key, value]) => value === undefined || QUILL_SUPPORTED_PROPS.has(key as keyof DateFilterProps)
        )

    if (featureFlags[FEATURE_FLAGS.DATEPICKER_COMPONENT] === 'quill' && quillCanRender) {
        return (
            <QuillDateFilter
                dateFrom={toDateString(props.dateFrom)}
                dateTo={toDateString(props.dateTo)}
                onChange={props.onChange}
                dataAttr={dataAttr}
            />
        )
    }

    return <LemonDatePicker ref={ref} dataAttr={dataAttr} {...props} />
})
