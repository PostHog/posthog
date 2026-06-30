import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { tagsModel } from '~/models/tagsModel'

import type { tagSelectLogicType } from './tagSelectLogicType'

export interface TagSelectLogicProps {
    logicKey: string
}

export const tagSelectLogic = kea<tagSelectLogicType>([
    props({} as TagSelectLogicProps),
    key((props) => props.logicKey),
    path((logicKey) => ['lib', 'components', 'tagSelectLogic', logicKey]),
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
