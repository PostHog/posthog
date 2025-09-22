import { actions, kea, key, path, props, reducers, selectors } from 'kea'

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
                setDates: (state, { date_from, date_to }) => ({ ...state, date_from, date_to }),
                setProperties: (state, { properties }) => ({ ...state, properties }),
                setBreakdown: (state, { breakdown_filter }) => ({ ...state, breakdown_filter }),
                resetOverrides: () => ({}),
            },
        ],
    })),

    selectors(() => ({
        /** For showing an "Overrides" chip if anything is set */
        hasOverrides: [
            (s) => [s.overrides],
            (o: TileFilters) => {
                // Check if any override has a meaningful value
                if (o.date_from !== undefined || o.date_to !== undefined || o.properties !== undefined) {
                    return true
                }
                // For breakdown_filter, check if it has meaningful values
                if (o.breakdown_filter !== undefined && o.breakdown_filter !== null) {
                    const bf = o.breakdown_filter
                    return !!(bf.breakdown || bf.breakdowns || bf.breakdown_type)
                }
                return false
            },
        ],
    })),
])
