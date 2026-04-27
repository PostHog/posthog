import { PersonDistinctIdsOutput, PersonsOutput } from '../../../ingestion/analytics/outputs'

export type PersonMessage = {
    output: PersonsOutput | PersonDistinctIdsOutput
    value: Buffer | null
}
