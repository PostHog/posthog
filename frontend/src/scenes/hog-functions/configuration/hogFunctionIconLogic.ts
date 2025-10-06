import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { HogFunctionIconResponse } from '~/types'

import type { hogFunctionIconLogicType } from './hogFunctionIconLogicType'

export interface HogFunctionIconLogicProps {
    logicKey: string
    src?: string
    onChange?: (src: string) => void
}

export const hogFunctionIconLogic = kea<hogFunctionIconLogicType>([
    props({} as HogFunctionIconLogicProps),
    key((props) => props.logicKey ?? 'default'),
    path((key) => ['scenes', 'pipeline', 'hogfunctions', 'hogFunctionIconLogic', key]),

    actions({
        loadPossibleIcons: true,
        setShowPopover: (show: boolean) => ({ show }),
        setSearchTerm: (search: string) => ({ search }),
    }),

    reducers({
        showPopover: [
            false,
            {
                setShowPopover: (_, { show }) => show,
            },
        ],

        searchTerm: [
            null as string | null,
            {
                setSearchTerm: (_, { search }) => search,
                setShowPopover: () => null,
            },
        ],
    }),

    loaders(({ values }) => ({
        possibleIcons: [
            null as HogFunctionIconResponse[] | null,
            {
                loadPossibleIcons: async (_, breakpoint) => {
                    const search = values.searchTerm

                    if (!search) {
                        return []
                    }

                    await breakpoint(1000)
                    const res = await api.hogFunctions.listIcons({ query: search })
                    return res.map((icon) => ({
                        ...icon,
                        url: icon.url + '&temp=true',
                    }))
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        setShowPopover: ({ show }) => {
            if (show) {
                actions.loadPossibleIcons()
            }
        },

        setSearchTerm: () => {
            actions.loadPossibleIcons()
        },
    })),
])
