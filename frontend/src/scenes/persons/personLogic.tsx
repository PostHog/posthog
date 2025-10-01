import { actions, kea, key, path, props } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'

import { hogql } from '~/queries/utils'
import { PersonType } from '~/types'

import type { personLogicType } from './personLogicType'

export interface PersonLogicProps {
    id: string | undefined
    distinctId: string
}

export interface Info {
    sessionCount: number
    eventCount: number
    lastSeen: string | null
}

export const personLogic = kea<personLogicType>([
    props({} as PersonLogicProps),
    key((props) => props.distinctId),
    path((key) => ['scenes', 'persons', 'personLogic', key]),
    actions({
        loadPerson: true,
        loadInfo: true,
    }),
    lazyLoaders(({ props }) => ({
        person: [
            null as PersonType | null,
            {
                loadPerson: async (): Promise<PersonType | null> => {
                    const response = await api.persons.list({ distinct_id: props.distinctId })
                    const person = response.results[0]
                    return person
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
