import { loaders } from 'kea-loaders'
import { kea, props, key, path, connect, actions, reducers, selectors, listeners, afterMount } from 'kea'
import api from 'lib/api'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { teamLogic } from 'scenes/teamLogic'
import { Noun, groupsModel } from '~/models/groupsModel'
import { Group } from '~/types'
import type { groupsListLogicType } from './groupsListLogicType'

export interface GroupsPaginatedResponse {
    next: string | null
    previous: string | null
    results: Group[]
}

export interface GroupsListLogicProps {
    groupTypeIndex: number
}

export const groupsListLogic = kea<groupsListLogicType>([
    props({} as GroupsListLogicProps),
    key((props: GroupsListLogicProps) => props.groupTypeIndex),
    path(['groups', 'groupsListLogic']),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            groupsAccessLogic,
            ['groupsEnabled'],
        ],
    }),
    actions(() => ({
        loadGroups: (url?: string | null) => ({ url }),
        setSearch: (search: string, debounce: boolean = true) => ({ search, debounce }),
    })),
    loaders(({ props, values }) => ({
        groups: [
            { next: null, previous: null, results: [] } as GroupsPaginatedResponse,
            {
                loadGroups: async ({ url }) => {
                    if (!values.groupsEnabled) {
                        return values.groups
                    }
                    url =
                        url ||
                        `api/projects/${values.currentTeamId}/groups/?group_type_index=${props.groupTypeIndex}${
                            values.search ? '&search=' + encodeURIComponent(values.search) : ''
                        }`
                    return await api.get(url)
                },
            },
        ],
    })),
    reducers({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
            },
        ],
    }),
    selectors({
        groupTypeName: [
            (s, p) => [p.groupTypeIndex, s.aggregationLabel],
            (groupTypeIndex, aggregationLabel): Noun =>
                groupTypeIndex === -1 ? { singular: 'person', plural: 'persons' } : aggregationLabel(groupTypeIndex),
        ],
    }),
    listeners(({ actions }) => ({
        setSearch: async ({ debounce }, breakpoint) => {
            if (debounce) {
                await breakpoint(300)
            }
            actions.loadGroups()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadGroups()
    }),
])
