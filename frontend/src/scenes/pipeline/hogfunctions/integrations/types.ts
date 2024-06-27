import { HogFunctionInputSchemaType } from '~/types'

export type HogFunctionInputIntegrationConfigureProps = {
    value?: any
    onChange?: (value: string | null) => void
}

export type HogFunctionInputIntegrationProps = HogFunctionInputIntegrationConfigureProps & {
    schema: HogFunctionInputSchemaType
}
