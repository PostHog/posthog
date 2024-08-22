import { HogFunctionInputSchemaType } from '~/types'

import { IntegrationChoice, IntegrationConfigureProps } from './IntegrationChoice'

export type HogFunctionInputIntegrationProps = IntegrationConfigureProps & {
    schema: HogFunctionInputSchemaType
}

export function HogFunctionInputIntegration({ schema, ...props }: HogFunctionInputIntegrationProps): JSX.Element {
    return (
        <IntegrationChoice
            {...props}
            integration={schema.integration}
            redirectUrl={`${window.location.pathname}?integration_target=${schema.key}`}
        />
    )
}
