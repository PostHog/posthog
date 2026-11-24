import { CyclotronJobInputSchemaType } from '~/types'

/** Empties the fields that read from an integration, since their values belong to the integration that was replaced. */
export function clearIntegrationFields(
    configuration: { inputs_schema: CyclotronJobInputSchemaType[] },
    integrationKey: string,
    onInputChange: (key: string, value: any) => void
): void {
    configuration.inputs_schema
        .filter((s) => s.type === 'integration_field' && s.integration_key === integrationKey)
        .forEach((field) => {
            onInputChange(field.key, { value: null })
        })
}
