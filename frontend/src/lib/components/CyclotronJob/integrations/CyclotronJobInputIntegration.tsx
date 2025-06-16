import { CyclotronJobInputSchemaType } from '~/types'

import { IntegrationChoice, IntegrationConfigureProps } from './IntegrationChoice'

export type CyclotronJobInputIntegrationProps = IntegrationConfigureProps & {
    schema: CyclotronJobInputSchemaType
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
            redirectUrl={`${window.location.pathname}?integration_target=${schema.key}`}
            beforeRedirect={() => persistForUnload?.()}
        />
    )
}
