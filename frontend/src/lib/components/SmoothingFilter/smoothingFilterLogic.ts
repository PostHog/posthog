import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { smoothingFilterLogicType } from './smoothingFilterLogicType'
import { intervalFilterLogic } from '../IntervalFilter/intervalFilterLogic'
import { SmoothingType } from '~/types'
import { smoothingOptions } from './smoothings'

export const smoothingFilterLogic = kea<smoothingFilterLogicType>({
    connect: {
        values: [intervalFilterLogic, ['interval']],
        actions: [intervalFilterLogic, ['setIntervalFilter']],
    },
    actions: () => ({
        setSmoothingFilter: (filter: SmoothingType) => ({ filter }),
    }),
    reducers: {
        smoothing: [
            1 as SmoothingType,
            {
                setSmoothingFilter: (_, { filter }) => filter,
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        setSmoothingFilter: () => {
            const { smoothing, ...searchParams } = router.values.searchParams
            const { pathname } = router.values.location

            searchParams.smoothing = values.smoothing

            if (!objectsEqual(smoothing, values.smoothing)) {
                router.actions.replace(pathname, searchParams, router.values.hashParams)
            }
        },
        setIntervalFilter: () => {
            if (values.interval === null) {
                return
            }
            if (!smoothingOptions[values.interval].find((option) => option.value === values.smoothing)) {
                if (values.smoothing !== 1) {
                    actions.setSmoothingFilter(1)
                }
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_, { smoothing }) => {
            if (smoothing) {
                actions.setSmoothingFilter(smoothing)
            }
        },
    }),
})
