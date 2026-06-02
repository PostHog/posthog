import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import type { poeFilterLogicType } from './poeFilterLogicType'

export type PoeModeTypes = HogQLQueryModifiers['personsOnEventsMode'] | null

export const poeFilterLogic = kea<poeFilterLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'EditorFilters', 'poeFilterLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [insightVizDataLogic(props), ['querySource']],
        actions: [insightVizDataLogic(props), ['updateQuerySource']],
    })),
    actions(() => ({
        setPoeMode: (poeMode: PoeModeTypes) => ({ poeMode }),
    })),
    reducers({
        poeMode: [
            null as PoeModeTypes,
            {
                setPoeMode: (_, { poeMode }) => poeMode || null,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setPoeMode: () => {
            const modifiers = { ...values.querySource?.modifiers }
            if (values.poeMode) {
                modifiers.personsOnEventsMode = values.poeMode
            } else {
                delete modifiers.personsOnEventsMode
            }

            actions.updateQuerySource({
                modifiers: Object.keys(modifiers).length ? modifiers : undefined,
            })
        },
    })),
    subscriptions(({ values, actions }) => ({
        querySource: (querySource) => {
            const newPoeMode = querySource?.modifiers?.personsOnEventsMode
            if ((!!newPoeMode || !!values.poeMode) && newPoeMode != values.poeMode) {
                actions.setPoeMode(newPoeMode)
            }
        },
    })),
])
