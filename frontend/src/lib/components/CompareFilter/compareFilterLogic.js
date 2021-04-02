import { kea } from 'kea'
import { router } from 'kea-router'
import { ShownAsValue } from 'lib/constants'
import { objectsEqual } from 'lib/utils'

export const compareFilterLogic = kea({
    actions: () => ({
        setCompare: (compare) => ({ compare }),
        setDisabled: (disabled) => ({ disabled }),
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
                router.actions.push(pathname, searchParams)
            }
        },
        toggleCompare: () => {
            actions.setCompare(!values.compare)
        },
    }),
    urlToAction: ({ actions }) => ({
        '/insights': (_, { compare, shown_as, date_from }) => {
            if (compare != null) {
                actions.setCompare(compare)
            }
            if (shown_as === ShownAsValue.LIFECYCLE || date_from === 'all') {
                actions.setDisabled(true)
            } else {
                actions.setDisabled(false)
            }
        },
    }),
})
