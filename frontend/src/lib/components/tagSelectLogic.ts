import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { tagsModel } from '~/models/tagsModel'

import type { tagSelectLogicType } from './tagSelectLogicType'

export const tagSelectLogic = kea<tagSelectLogicType>([
    path(['lib', 'components', 'tagSelectLogic']),
    connect(() => ({
        values: [tagsModel, ['tags']],
    })),
    actions(() => ({
        setSearch: (search: string) => ({ search }),
        setShowPopover: (visible: boolean) => ({ visible }),
    })),
    reducers(() => ({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
                setShowPopover: (state, { visible }) => (visible ? state : ''), // Clear search when closing
            },
        ],
        showPopover: [
            false,
            {
                setShowPopover: (_, { visible }) => visible,
            },
        ],
    })),
    selectors(() => ({
        filteredTags: [
            (s) => [s.tags, s.search],
            (tags, search) => {
                if (!search) {
                    return tags || []
                }
                return (tags || []).filter((tag) => tag.toLowerCase().includes(search.toLowerCase()))
            },
        ],
    })),
])
