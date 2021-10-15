import { IntervalType } from '~/types'

// Lists the valid smoothing intervals value for each interval type. Note that
// the typing should catch if we update IntervalType but do not add an explicit
// option to this lookup
export const smoothingOptions: Record<IntervalType, { label: string; value: number }[]> = {
    minute: [
        {
            label: 'No smoothing',
            value: 1,
        },
        {
            label: '5 Min',
            value: 5,
        },
        {
            label: '60 Min',
            value: 60,
        },
    ],
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
