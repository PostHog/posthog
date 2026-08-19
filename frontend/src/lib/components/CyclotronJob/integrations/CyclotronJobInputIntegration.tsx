import { CyclotronJobInputSchemaType } from '~/types'

import { IntegrationChoice, IntegrationConfigureProps } from './IntegrationChoice'

function buildRedirectUrl(integrationTarget: string): string {
    const params = new URLSearchParams(window.location.search)
    params.set('integration_target', integrationTarget)
    return `${window.location.pathname}?${params.toString()}${window.location.hash}`
}

export type CyclotronJobInputIntegrationProps = IntegrationConfigureProps & {
    schema: CyclotronJobInputSchemaType
    // Connecting an integration navigates the whole page to OAuth, which destroys form state. The
    // host saves it here so the round trip can restore it.
    persistForUnload?: () => void
}

export function CyclotronJobInputIntegration({
    schema,
    persistForUnload,
    ...props
}: CyclotronJobInputIntegrationProps): JSX.Element {
    return (
        <IntegrationChoice
            {...props}
            schema={schema}
            integration={schema.integration}
            redirectUrl={buildRedirectUrl(schema.key)}
            beforeRedirect={() => persistForUnload?.()}
        />
    )
}
