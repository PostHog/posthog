import { kea } from 'kea'
import { router } from 'kea-router'
import { objectsEqual } from 'lib/utils'

export const compareFilterLogic = kea({
    actions: () => ({
        setCompare: (compare) => ({ compare }),
    }),
    reducers: ({ actions }) => ({
        compare: [
            false,
            {
                [actions.setCompare]: (_, { compare }) => compare,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        [actions.setCompare]: () => {
            const { compare, ...searchParams } = router.values.searchParams // eslint-disable-line
            const { pathname } = router.values.location

            searchParams.compare = values.compare

            if (!objectsEqual(compare, values.compare)) {
                router.actions.push(pathname, searchParams)
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/trends': (_, { compare }) => {
            if (compare) actions.setCompare(compare)
        },
    }),
})
