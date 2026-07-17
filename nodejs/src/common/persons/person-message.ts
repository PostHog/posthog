import { PersonDistinctIdsOutput, PersonsOutput } from '~/common/outputs/persons'

export type PersonMessage = {
    output: PersonsOutput | PersonDistinctIdsOutput
    value: Buffer | null
}
