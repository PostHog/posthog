import { IntervalType, SmoothingType } from '~/types'

// Lists the valid smoothing intervals value for each interval type. Note that
// the typing should catch if we update SmoothingType but do not add an explicit
// option to this lookup
export const smoothingOptions: Record<IntervalType, { label: string; value: SmoothingType }[]> = {
    minute: [
        {
            label: 'No smoothing',
            value: 1,
        },
        {
            label: '5-minute average',
            value: 5,
        },
    ],
    hour: [
        {
            label: 'No smoothing',
            value: 1,
        },
        {
            label: '24-hour average',
            value: 24,
        },
    ],
    day: [
        {
            label: 'No smoothing',
            value: 1,
        },
        {
            label: '7-day average',
            value: 7,
        },
        {
            label: '28-day average',
            value: 28,
        },
    ],
    week: [],
    month: [],
}

export type SmoothingKeyType = keyof typeof smoothingOptions
