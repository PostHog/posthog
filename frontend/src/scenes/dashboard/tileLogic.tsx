import { actions, kea, key, path, props, reducers } from 'kea'

import { BreakdownFilter, TileFilters } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

import type { tileLogicType } from './tileLogicType'

export interface TileLogicProps {
    dashboardId: number
    tileId: number
    filtersOverrides?: TileFilters
}

export const tileLogic = kea<tileLogicType>([
    path(['scenes', 'dashboard', 'tileLogic']),
    props({} as TileLogicProps),
    key((p: TileLogicProps) => `${p.dashboardId}:${p.tileId}`),

    actions(() => ({
        setDates: (date_from: string | null | undefined, date_to: string | null | undefined) => ({
            date_from,
            date_to,
        }),
        setProperties: (properties: AnyPropertyFilter[] | null | undefined) => ({ properties }),
        setBreakdown: (breakdown_filter: BreakdownFilter | null | undefined) => ({ breakdown_filter }),
        resetOverrides: true,
    })),

    reducers(({ props }) => ({
        overrides: [
            (props.filtersOverrides ?? {}) as TileFilters,
            {
                setDates: (state, { date_from, date_to }) => {
                    const newState = { ...state }
                    if (date_from !== undefined && date_from !== null) {
                        newState.date_from = date_from
                    } else {
                        delete newState.date_from
                    }
                    if (date_to !== undefined && date_to !== null) {
                        newState.date_to = date_to
                    } else {
                        delete newState.date_to
                    }
                    return newState
                },
                setProperties: (state, { properties }) => {
                    const newState = { ...state }
                    if (properties && properties.length > 0) {
                        newState.properties = properties
                    } else {
                        delete newState.properties
                    }
                    return newState
                },
                setBreakdown: (state, { breakdown_filter }) => ({ ...state, breakdown_filter }),
                resetOverrides: () => ({}),
            },
        ],
    })),
])
