import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

export const isEmptyInputValue = (value: unknown): boolean =>
    value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)

/**
 * Fill in `inputs` entries from their schema's `default` wherever the current value is empty.
 * Applying a new schema without this leaves a required field with a declared default failing
 * validation even though the form shows the default — the user has to retype it to recover.
 */
export function seedInputsFromSchemaDefaults(
    inputsSchema: CyclotronJobInputSchemaType[],
    inputs: Record<string, CyclotronJobInputType>
): Record<string, CyclotronJobInputType> {
    const seeded = { ...inputs }
    for (const schema of inputsSchema) {
        if (schema.default === undefined || !schema.key) {
            continue
        }
        const existing = seeded[schema.key]
        if (isEmptyInputValue(existing?.value)) {
            seeded[schema.key] = { ...existing, value: schema.default }
        }
    }
    return seeded
}
