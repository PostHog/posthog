import { actions, kea, key, path, props, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { hogqlQuery } from '~/queries/query'
import { hogql } from '~/queries/utils'
import { Breadcrumb, PersonType } from '~/types'

import { getHogqlQueryStringForPersonId } from './person-utils'
import type { personLogicType } from './personLogicType'

export interface PersonLogicProps {
    id: string | undefined
    distinctId: string | undefined
}

export interface Info {
    sessionCount: number
    eventCount: number
    lastSeen: string | null
}

export const personLogic = kea<personLogicType>([
    props({} as PersonLogicProps),
    key((props) => props.distinctId ?? props.id ?? 'undefined'),
    path((key) => ['scenes', 'persons', 'personLogic', key]),
    actions({
        loadPerson: true,
        loadInfo: true,
    }),
    selectors(() => ({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = [
                    {
                        key: Scene.Person,
                        name: sceneConfigurations[Scene.Person].name,
                        iconType: sceneConfigurations[Scene.Person].iconType || 'default_icon_type',
                    },
                ]

                return breadcrumbs
            },
        ],
    })),
    lazyLoaders(({ props }) => ({
        person: [
            null as PersonType | null,
            {
                loadPerson: async (): Promise<PersonType | null> => {
                    if (props.distinctId != null) {
                        const response = await api.persons.list({ distinct_id: props.distinctId })
                        const person = response.results[0]
                        if (person != null) {
                            return person
                        }
                    }
                    if (props.id == null) {
                        return null
                    }
                    const queryResponse = await hogqlQuery(
                        getHogqlQueryStringForPersonId(),
                        { id: props.id },
                        'blocking'
                    )
                    const row = queryResponse?.results?.[0]
                    if (row == null) {
                        return null
                    }
                    const queryPerson: PersonType = {
                        id: row[0],
                        uuid: row[0],
                        distinct_ids: row[1],
                        properties: JSON.parse(row[2] || '{}'),
                        is_identified: !!row[3],
                        created_at: row[4],
                    }
                    return queryPerson
                },
            },
        ],
        info: [
            null as Info | null,
            {
                loadInfo: async (): Promise<Info | null> => {
                    if (!props.id) {
                        return null
                    }

                    const infoQuery = hogql`
                    SELECT
                        count(DISTINCT $session_id) as session_count,
                        count(*) as event_count,
                        max(timestamp) as last_seen
                    FROM events
                    WHERE person_id = ${props.id}
                    AND timestamp >= now() - interval 30 day
                    `
                    try {
                        const response = await api.queryHogQL(infoQuery)
                        const row = response.results?.[0]
                        if (!row) {
                            return {
                                sessionCount: 0,
                                eventCount: 0,
                                lastSeen: null,
                            }
                        }

                        const [sessionCount, eventCount, lastSeen] = row
                        return { sessionCount, eventCount, lastSeen }
                    } catch (error: any) {
                        posthog.captureException(error)
                        return {
                            sessionCount: 0,
                            eventCount: 0,
                            lastSeen: null,
                        }
                    }
                },
            },
        ],
    })),
])
