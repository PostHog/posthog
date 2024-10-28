import FuseClass from 'fuse.js'
import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { teamLogic } from 'scenes/teamLogic'

import { HogFunctionType, HogFunctionTypeType } from '~/types'

import type { functionsTableLogicType } from './functionsTableLogicType'

// Helping kea-typegen navigate the exported default class for Fuse
export interface Fuse extends FuseClass<HogFunctionType> {}

export interface FunctionsTableLogicProps {
    type?: HogFunctionTypeType
}
export interface HogFunctionsFilter {
    search?: string
}
export const functionsTableLogic = kea<functionsTableLogicType>([
    path(['scenes', 'messaging', 'functionsTableLogic']),
    props({} as FunctionsTableLogicProps),
    key((props: FunctionsTableLogicProps) => props.type ?? 'destination'),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        deleteHogFunction: (hogFunction: HogFunctionType) => ({ hogFunction }),
        setFilters: (filters: Partial<HogFunctionsFilter>) => ({ filters }),
        resetFilters: true,
    }),
    reducers({
        filters: [
            {} as HogFunctionsFilter,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                resetFilters: () => ({}),
            },
        ],
    }),
    loaders(({ props, values, actions }) => ({
        hogFunctions: [
            [] as HogFunctionType[],
            {
                loadHogFunctions: async () => {
                    // TODO: pagination?
                    return (await api.hogFunctions.list({ type: props.type ?? 'destination' })).results
                },
                deleteHogFunction: async ({ hogFunction }) => {
                    await deleteWithUndo({
                        endpoint: `projects/${teamLogic.values.currentTeamId}/hog_functions`,
                        object: {
                            id: hogFunction.id,
                            name: hogFunction.name,
                        },
                        callback: (undo) => {
                            if (undo) {
                                actions.loadHogFunctions()
                            }
                        },
                    })
                    return values.hogFunctions.filter((hf) => hf.id !== hogFunction.id)
                },
            },
        ],
    })),
    selectors({
        loading: [(s) => [s.hogFunctionsLoading], (hogFunctionsLoading) => hogFunctionsLoading],
        hogFunctionsFuse: [
            (s) => [s.hogFunctions],
            (hogFunctions): Fuse => {
                return new FuseClass(hogFunctions || [], {
                    keys: ['name', 'description'],
                    threshold: 0.3,
                })
            },
        ],

        filteredHogFunctions: [
            (s) => [s.filters, s.hogFunctions, s.hogFunctionsFuse],
            (filters, hogFunctions, hogFunctionsFuse): HogFunctionType[] => {
                const { search } = filters
                return search ? hogFunctionsFuse.search(search).map((x) => x.item) : hogFunctions
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadHogFunctions()
    }),
])
