import { useActions } from 'kea'

import { HogFunctionInputSchemaType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { IntegrationChoice, IntegrationConfigureProps } from './IntegrationChoice'

export type HogFunctionInputIntegrationProps = IntegrationConfigureProps & {
    schema: HogFunctionInputSchemaType
}

export function HogFunctionInputIntegration({ schema, ...props }: HogFunctionInputIntegrationProps): JSX.Element {
    const { disableBeforeUnload } = useActions(hogFunctionConfigurationLogic)
    return (
        <IntegrationChoice
            {...props}
            integration={schema.integration}
            redirectUrl={`${window.location.pathname}?integration_target=${schema.key}`}
            beforeRedirect={() => disableBeforeUnload()}
        />
    )
}
