import { useActions } from 'kea'

import { CyclotronJobInputSchemaType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'
import { IntegrationChoice, IntegrationConfigureProps } from './IntegrationChoice'

export type HogFunctionInputIntegrationProps = IntegrationConfigureProps & {
    schema: CyclotronJobInputSchemaType
}

export function HogFunctionInputIntegration({ schema, ...props }: HogFunctionInputIntegrationProps): JSX.Element {
    const { persistForUnload } = useActions(hogFunctionConfigurationLogic)
    return (
        <>
            <IntegrationChoice
                {...props}
                schema={schema}
                integration={schema.integration}
                redirectUrl={`${window.location.pathname}?integration_target=${schema.key}`}
                beforeRedirect={() => persistForUnload()}
            />
        </>
    )
}
