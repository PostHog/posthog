import { IntervalType, SmoothingType } from '~/types'

// Lists the valid smoothing intervals value for each interval type. Note that
// the typing should catch if we update SmoothingType but do not add an explicit
// option to this lookup
export const smoothingOptions: Record<IntervalType, { label: string; value: SmoothingType }[]> = {
    hour: [
        {
            label: 'No smoothing',
            value: 1,
        },
        {
            label: '24 Hrs',
            value: 24,
        },
    ],
    day: [
        {
            label: 'No smoothing',
            value: 1,
        },
        {
            label: '7 Day',
            value: 7,
        },
        {
            label: '28 Day',
            value: 28,
        },
    ],
    week: [],
    month: [],
}

export type SmoothingKeyType = keyof typeof smoothingOptions
