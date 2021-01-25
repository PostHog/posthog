import { kea } from 'kea'
import { router } from 'kea-router'
import { topContentLogicType } from './topContentLogicType'

interface BackTo {
    display: string
    url: string
}

export const topContentLogic = kea<topContentLogicType<BackTo>>({
    actions: {
        setBackTo: (payload) => ({ payload }),
    },

    reducers: {
        backTo: [
            null as BackTo | null,
            {
                setBackTo: (_, { payload }) => payload,
            },
        ],
    },
    listeners: ({ actions }) => ({
        [router.actionTypes.locationChanged]: ({ hashParams }) => {
            if (!hashParams.backTo || !hashParams.backToURL) {
                actions.setBackTo(null)
            } else {
                actions.setBackTo({ display: hashParams.backTo, url: hashParams.backToURL })
            }
        },
    }),
})
