import { PersonDistinctIdsOutput, PersonsOutput } from '~/outputs/persons'

export type PersonMessage = {
    output: PersonsOutput | PersonDistinctIdsOutput
    value: Buffer | null
}
