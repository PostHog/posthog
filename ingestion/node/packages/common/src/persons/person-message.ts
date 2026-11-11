import { PersonDistinctIdsOutput, PersonsOutput } from '@posthog/node-common/outputs/persons'

export type PersonMessage = {
    output: PersonsOutput | PersonDistinctIdsOutput
    value: Buffer | null
}
