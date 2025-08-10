import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

// Abstract type to keep this component agnostic of the use case
export type CyclotronJobInputConfiguration = {
    inputs_schema: CyclotronJobInputSchemaType[]
    inputs: Record<string, CyclotronJobInputType> | null
}
