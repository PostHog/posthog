import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { InsightType } from '~/types'
import { compareFilterLogicType } from './compareFilterLogicType'

export const compareFilterLogic = kea<compareFilterLogicType>({
    path: ['lib', 'components', 'CompareFilter', 'compareFilterLogic'],
    actions: () => ({
        setCompare: (compare: boolean) => ({ compare }),
        setDisabled: (disabled: boolean) => ({ disabled }),
        toggleCompare: true,
        init: (searchParams: Record<string, any>) => ({ searchParams }),
    }),
    reducers: () => ({
        compare: [
            false,
            {
                setCompare: (_, { compare }) => compare,
            },
        ],
        disabled: [
            false,
            {
                setDisabled: (_, { disabled }) => disabled,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        init: ({ searchParams: { compare, date_from, insight } }) => {
            if (compare !== undefined) {
                actions.setCompare(compare)
            }
            if (insight === InsightType.LIFECYCLE || date_from === 'all') {
                actions.setDisabled(true)
            } else {
                actions.setDisabled(false)
            }
        },
        setCompare: () => {
            const { compare, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.compare = values.compare

            if (!objectsEqual(compare, values.compare)) {
                router.actions.replace(pathname, searchParams, router.values.hashParams)
            }
        },
        toggleCompare: () => {
            actions.setCompare(!values.compare)
        },
        [router.actionTypes.locationChanged]: ({ searchParams }) => {
            actions.init(searchParams)
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.init(router.values.searchParams)
        },
    }),
})
