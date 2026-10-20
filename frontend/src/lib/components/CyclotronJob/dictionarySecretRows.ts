import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

// The API returns this in place of each stored secret entry, and restores the stored value when it comes back.
export const MASKED_SECRET_VALUE = '********'

// `stored` rows already have a saved value; `masked` ones still show it as hidden.
export type SecretDictionaryRow = { key: string; value: string; masked: boolean; stored: boolean }

// A secret dictionary input named `secret_<key>` holds the rows of the plain `<key>` dictionary that the user made secret.
export function findSecretRowsCompanion(
    schema: CyclotronJobInputSchemaType,
    inputsSchema: CyclotronJobInputSchemaType[] | undefined
): CyclotronJobInputSchemaType | undefined {
    if (schema.type !== 'dictionary' || schema.secret) {
        return undefined
    }
    return inputsSchema?.find((s) => s.key === `secret_${schema.key}` && s.type === 'dictionary' && s.secret)
}

export function isSecretRowsCompanion(
    schema: CyclotronJobInputSchemaType,
    inputsSchema: CyclotronJobInputSchemaType[] | undefined
): boolean {
    return !!inputsSchema?.some((s) => findSecretRowsCompanion(s, inputsSchema) === schema)
}

export function secretEntries(input: CyclotronJobInputType | undefined): Record<string, unknown> | undefined {
    const value = input?.value
    return value && typeof value === 'object' && !Array.isArray(value) ? value : undefined
}

// A stored secret that comes back without its keys (a draft) cannot take a new row without losing the stored ones.
export function canAddSecretRow(secretInput: CyclotronJobInputType | undefined): boolean {
    return !secretInput?.secret || !!secretEntries(secretInput)
}

export function secretRowsFromInput(input: CyclotronJobInputType): SecretDictionaryRow[] {
    return Object.entries(secretEntries(input) ?? {}).map(([key, value]) =>
        value === MASKED_SECRET_VALUE
            ? { key, value: '', masked: true, stored: true }
            : { key, value: String(value ?? ''), masked: false, stored: false }
    )
}

export function secretRowsToValue(rows: SecretDictionaryRow[]): Record<string, string> {
    return Object.fromEntries(
        rows
            .filter((r) => r.masked || r.key.trim() !== '' || r.value.trim() !== '')
            // A stored row the user opened with Replace but left empty keeps its stored value.
            .map((r) => [r.key, r.masked || (r.stored && r.value === '') ? MASKED_SECRET_VALUE : r.value])
    )
}
