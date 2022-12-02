import { actions, kea, path, reducers } from 'kea'

import type { eventsSceneLogicType } from './eventsSceneLogicType'
import { AnyPropertyFilter, PropertyFilter } from '~/types'
import { actionToUrl, router, urlToAction } from 'kea-router'
import equal from 'fast-deep-equal'

export const eventsSceneLogic = kea<eventsSceneLogicType>([
    path(['scenes', 'events', 'eventsSceneLogic']),

    actions({
        setProperties: (properties: AnyPropertyFilter[]) => ({ properties }),
        setEventFilter: (event: string) => ({ event }),
        setColumns: (columns: string[] | null) => ({ columns }),
    }),
    reducers({
        properties: [
            [] as PropertyFilter[],
            {
                setProperties: (_, { properties }) => properties as PropertyFilter[],
            },
        ],
        eventFilter: [
            '',
            {
                setEventFilter: (_, { event }) => event,
            },
        ],
        columns: [
            null as null | string[],
            {
                setColumns: (_, { columns }) => columns,
            },
        ],
    }),
    actionToUrl(({ values }) => ({
        setProperties: () => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    properties: values.properties.length === 0 ? undefined : values.properties,
                },
                router.values.hashParams,
                { replace: true },
            ]
        },
        setEventFilter: () => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    eventFilter: values.eventFilter || undefined,
                },
                router.values.hashParams,
                { replace: true },
            ]
        },
    })),

    urlToAction(({ actions, values }) => ({
        '*': (_: Record<string, any>, searchParams: Record<string, any>): void => {
            const nextProperties = searchParams.properties || values.properties || {}
            if (!equal(nextProperties, values.properties)) {
                actions.setProperties(nextProperties)
            }

            const nextEventFilter = searchParams.eventFilter || ''
            if (!equal(nextEventFilter, values.eventFilter)) {
                actions.setEventFilter(nextEventFilter)
            }
        },
    })),
])
