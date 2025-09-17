import { Message } from 'node-rdkafka'

import { instrumented } from '~/common/tracing/tracing-utils'
import { UUIDT } from '~/utils/utils'

import { KAFKA_PERSON } from '../../config/kafka-topics'
import { ClickHousePerson, Hub, Team } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { CyclotronPerson, HogFunctionInvocationGlobals, HogFunctionType, HogFunctionTypeType } from '../types'
import { getPersonDisplayName } from '../utils'
import { CdpEventsConsumer, counterParseError } from './cdp-events.consumer'

export class CdpPersonUpdatesConsumer extends CdpEventsConsumer {
    protected name = 'CdpPersonUpdatesConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    constructor(hub: Hub) {
        super(hub, KAFKA_PERSON, 'cdp-person-updates-consumer')
    }

    protected filterHogFunction(hogFunction: HogFunctionType): boolean {
        return hogFunction.filters?.source === 'person-updates'
    }

    // This consumer always parses from kafka
    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        return await this.runWithHeartbeat(async () => {
            const globals: HogFunctionInvocationGlobals[] = []
            await Promise.all(
                messages.map(async (message) => {
                    try {
                        const data = parseJSON(message.value!.toString()) as ClickHousePerson

                        const [teamHogFunctions, team] = await Promise.all([
                            this.hogFunctionManager.getHogFunctionsForTeam(data.team_id, ['destination']),
                            this.hub.teamManager.getTeam(data.team_id),
                        ])

                        const filteredHogFunctions = teamHogFunctions.filter(this.filterHogFunction)

                        if (!filteredHogFunctions.length || !team) {
                            return
                        }

                        globals.push(convertClickhousePersonToInvocationGlobals(data, team, this.hub.SITE_URL))
                    } catch (e) {
                        logger.error('Error parsing message', e)
                        counterParseError.labels({ error: e.message }).inc()
                    }
                })
            )

            return globals
        })
    }
}

function convertClickhousePersonToInvocationGlobals(
    data: ClickHousePerson,
    team: Team,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const projectUrl = `${siteUrl}/project/${team.id}`

    const person: CyclotronPerson = {
        id: data.id,
        properties: parseJSON(data.properties),
        name: '',
        url: '',
    }

    person.name = getPersonDisplayName(team, person.id, person.properties)
    person.url = `${projectUrl}/person/${person.id}`

    const context: HogFunctionInvocationGlobals = {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            uuid: new UUIDT().toString(),
            event: '$person_updated',
            distinct_id: person.id,
            properties: {},
            timestamp: data.timestamp,
            url: person.url,
            elements_chain: '',
        },
        person,
    }

    return context
}
