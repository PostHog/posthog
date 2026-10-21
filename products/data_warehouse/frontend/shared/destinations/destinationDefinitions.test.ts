import {
    CREATABLE_DESTINATION_TYPES,
    WAREHOUSE_DESTINATIONS,
    buildDestinationConfig,
    buildDestinationFormValues,
    validateDestinationFields,
} from './destinationDefinitions'
import type { CreatableDestinationType } from './types'

describe('warehouse destination definitions', () => {
    it.each(CREATABLE_DESTINATION_TYPES)('%s keys its own definition', (type) => {
        expect(WAREHOUSE_DESTINATIONS[type].type).toEqual(type)
    })

    it.each(CREATABLE_DESTINATION_TYPES)('%s names at least one integration kind', (type) => {
        expect(WAREHOUSE_DESTINATIONS[type].integrationKinds.length).toBeGreaterThan(0)
    })

    it.each(CREATABLE_DESTINATION_TYPES)('%s only pins config keys it actually writes', (type) => {
        // A retargeting key the type never sends is never compared, so the backend guard for it
        // would never fire and the field would look protected while being editable.
        const { configKeys, retargetingKeys } = WAREHOUSE_DESTINATIONS[type]
        expect(configKeys).toEqual(expect.arrayContaining(retargetingKeys))
    })

    it.each(CREATABLE_DESTINATION_TYPES)('%s requires only fields it declares as config', (type) => {
        // A required field outside `configKeys` is dropped from the payload, so it can never be satisfied.
        const definition = WAREHOUSE_DESTINATIONS[type]
        const required = definition.requiredFields({ isNew: true, formValues: {} })
        expect(definition.configKeys).toEqual(expect.arrayContaining(required))
    })

    describe('buildDestinationConfig', () => {
        it('drops fields belonging to another type', () => {
            const config = buildDestinationConfig(WAREHOUSE_DESTINATIONS.BigQuery, {
                dataset: 'analytics',
                database: 'postgres',
                schema: 'public',
                bucket: 'my-bucket',
            })

            expect(config).toEqual({ dataset: 'analytics' })
        })

        it('leaves an untouched optional field out so the writer default applies', () => {
            // Snowflake falls back to the user's default role when `role` is absent. An empty
            // string is not absent, and would be asserted as an identifier.
            const config = buildDestinationConfig(WAREHOUSE_DESTINATIONS.Snowflake, {
                database: 'DB',
                schema: 'PUBLIC',
                warehouse: 'WH',
                role: '',
            })

            expect(config).not.toHaveProperty('role')
        })

        it('keeps a false checkbox rather than treating it as unset', () => {
            const config = buildDestinationConfig(WAREHOUSE_DESTINATIONS.S3, {
                bucket: 'b',
                region: 'us-east-1',
                use_virtual_style_addressing: false,
            })

            expect(config.use_virtual_style_addressing).toBe(false)
        })
    })

    describe('buildDestinationFormValues', () => {
        it.each(CREATABLE_DESTINATION_TYPES)('%s round-trips a saved config back into the form', (type) => {
            // A key missing from `configKeys` renders as the default, then overwrites the real value on save.
            const definition = WAREHOUSE_DESTINATIONS[type]
            const stored = Object.fromEntries(definition.configKeys.map((key) => [key, `stored-${key}`]))

            const formValues = buildDestinationFormValues(definition, stored)

            expect(buildDestinationConfig(definition, formValues)).toEqual(stored)
        })

        it('falls back to the type default when the key is absent', () => {
            const formValues = buildDestinationFormValues(WAREHOUSE_DESTINATIONS.Databricks, {})

            expect(formValues.catalog).toEqual('main')
            expect(formValues.volume).toEqual('posthog_warehouse_sync')
        })
    })

    describe('validateDestinationFields', () => {
        it.each(CREATABLE_DESTINATION_TYPES)('%s reports every required field on an empty form', (type) => {
            const definition = WAREHOUSE_DESTINATIONS[type]
            const required = definition.requiredFields({ isNew: true, formValues: {} })

            const errors = validateDestinationFields(definition, { isNew: true, formValues: {} })

            expect(Object.keys(errors).sort()).toEqual([...required].sort())
        })

        it('accepts a form filled from the type defaults plus its required fields', () => {
            const definition = WAREHOUSE_DESTINATIONS.Snowflake
            const formValues = { ...definition.defaults(), database: 'DB', warehouse: 'WH' }

            expect(validateDestinationFields(definition, { isNew: true, formValues })).toEqual({})
        })

        it('treats a whitespace-only value as missing', () => {
            const errors = validateDestinationFields(WAREHOUSE_DESTINATIONS.BigQuery, {
                isNew: true,
                formValues: { dataset: '   ' },
            })

            expect(errors.dataset).toBeTruthy()
        })
    })

    it('does not offer the managed PostHog warehouse as a type', () => {
        expect(CREATABLE_DESTINATION_TYPES).not.toContain('PostHogWarehouse' as CreatableDestinationType)
    })
})
