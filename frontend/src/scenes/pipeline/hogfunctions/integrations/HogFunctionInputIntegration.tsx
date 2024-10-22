import { useActions } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { HogFunctionInputSchemaType } from '~/types'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { IntegrationChoice, IntegrationConfigureProps } from './IntegrationChoice'

export type HogFunctionInputIntegrationProps = IntegrationConfigureProps & {
    schema: HogFunctionInputSchemaType
}

export function HogFunctionInputIntegration({ schema, ...props }: HogFunctionInputIntegrationProps): JSX.Element {
    const { persistForUnload } = useActions(hogFunctionConfigurationLogic)
    return (
        <>
            <IntegrationChoice
                {...props}
                integration={schema.integration}
                redirectUrl={`${window.location.pathname}?integration_target=${schema.key}`}
                beforeRedirect={() => persistForUnload()}
            />
            {schema.type === 'integration' && schema.integration === 'google-ads' ? (
                <LemonBanner type="warning">
                    <span>
                        We are still waiting for our Google Ads integration to be approved. You might see a `Google
                        hasn’t verified this app` warning when trying to connect your account.
                    </span>
                </LemonBanner>
            ) : null}
        </>
    )
}
