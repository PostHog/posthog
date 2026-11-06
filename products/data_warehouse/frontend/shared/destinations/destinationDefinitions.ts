import { azureBlobDefinition } from './azureBlob'
import { bigqueryDefinition } from './bigquery'
import { databricksDefinition } from './databricks'
import { postgresDefinition } from './postgres'
import { redshiftDefinition } from './redshift'
import { s3Definition } from './s3'
import { snowflakeDefinition } from './snowflake'
import type { CreatableDestinationType, DestinationContext, WarehouseDestinationDefinition } from './types'

/**
 * Adding a type here makes it selectable, but the backend decides whether it can be written:
 * `USER_CREATABLE_TYPES` in the destination serializer, and a registered writer in
 * `builtin_writers.py`. A type missing either fails on save rather than on sync.
 */
export const WAREHOUSE_DESTINATIONS: Record<CreatableDestinationType, WarehouseDestinationDefinition> = {
    Postgres: postgresDefinition,
    Redshift: redshiftDefinition,
    Snowflake: snowflakeDefinition,
    BigQuery: bigqueryDefinition,
    Databricks: databricksDefinition,
    S3: s3Definition,
    AzureBlob: azureBlobDefinition,
}

export const CREATABLE_DESTINATION_TYPES = Object.keys(WAREHOUSE_DESTINATIONS) as CreatableDestinationType[]

export function buildDestinationConfig(
    definition: WarehouseDestinationDefinition,
    formValues: Record<string, any>
): Record<string, any> {
    if (definition.serialize) {
        return definition.serialize(formValues)
    }

    const config: Record<string, any> = {}
    for (const key of definition.configKeys) {
        const value = formValues[key]
        // An untouched optional field stays out, so the writer's own default applies.
        if (value !== undefined && value !== null && value !== '') {
            config[key] = value
        }
    }
    return config
}

export function buildDestinationFormValues(
    definition: WarehouseDestinationDefinition,
    config: Record<string, any>
): Record<string, any> {
    if (definition.deserialize) {
        return { ...definition.defaults(), ...definition.deserialize(config) }
    }

    const values: Record<string, any> = { ...definition.defaults() }
    for (const key of definition.configKeys) {
        if (config[key] !== undefined) {
            values[key] = config[key]
        }
    }
    return values
}

export function validateDestinationFields(
    definition: WarehouseDestinationDefinition,
    ctx: DestinationContext
): Record<string, string | undefined> {
    const errors: Record<string, string | undefined> = {}

    for (const field of definition.requiredFields(ctx)) {
        const value = ctx.formValues[field]
        if (value === undefined || value === null || String(value).trim() === '') {
            errors[field] = 'This field is required'
        }
    }

    for (const [field, error] of Object.entries(definition.validate?.(ctx.formValues) ?? {})) {
        if (error && !errors[field]) {
            errors[field] = error
        }
    }

    return errors
}
