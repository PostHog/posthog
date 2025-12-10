import { IncomingEventWithTeam } from '../../types'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createFilterIpPropertiesStep<T extends { eventWithTeam: IncomingEventWithTeam }>(): ProcessingStep<
    T,
    T
> {
    return async function filterIpPropertiesStep(input) {
        const { eventWithTeam } = input
        const { event, team } = eventWithTeam

        if (event.properties?.$ip && team.anonymize_ips) {
            const { $ip, ...propertiesWithoutIp } = event.properties
            return Promise.resolve(
                ok({
                    ...input,
                    eventWithTeam: {
                        ...eventWithTeam,
                        event: {
                            ...event,
                            properties: propertiesWithoutIp,
                        },
                    },
                })
            )
        }

        return Promise.resolve(ok(input))
    }
}
