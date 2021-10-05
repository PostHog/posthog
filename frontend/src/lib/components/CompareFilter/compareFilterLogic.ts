import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'
import { FilterType, ViewType } from '~/types'
import { compareFilterLogicType } from './compareFilterLogicType'

export const compareFilterLogic = kea<compareFilterLogicType>({
    actions: () => ({
        setCompare: (compare: boolean) => ({ compare }),
        setDisabled: (disabled: boolean) => ({ disabled }),
        toggleCompare: true,
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
        setCompare: () => {
            const { compare, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.compare = values.compare

            if (!objectsEqual(compare, values.compare)) {
                router.actions.replace(pathname, searchParams)
            }
        },
        toggleCompare: () => {
            actions.setCompare(!values.compare)
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_, searchParams, hashParams) => {
            const { compare, insight, date_from }: Partial<FilterType> = { ...searchParams, ...hashParams.q }
            if (compare !== undefined) {
                actions.setCompare(compare)
            }
            if (insight === ViewType.LIFECYCLE || date_from === 'all') {
                actions.setDisabled(true)
            } else {
                actions.setDisabled(false)
            }
        },
    }),
})
