import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

// The API returns this in place of each stored secret entry, and restores the stored value when it comes back.
export const MASKED_SECRET_VALUE = '********'

export type DictionaryRow = { key: string; value: any; secret: boolean; masked: boolean }

type SecretRowsConfiguration = {
    inputs_schema?: CyclotronJobInputSchemaType[]
    inputs?: Record<string, CyclotronJobInputType> | null
}

// A secret dictionary input named `secret_<key>` holds the rows of the `<key>` dictionary that the user locked.
// A stored secret that comes back without its keys (a draft) cannot be shown row by row, so both inputs render as they are.
export function findSecretRowsCompanion(
    schema: CyclotronJobInputSchemaType,
    configuration: SecretRowsConfiguration
): CyclotronJobInputSchemaType | undefined {
    if (schema.type !== 'dictionary' || schema.secret) {
        return undefined
    }
    const companion = configuration.inputs_schema?.find(
        (s) => s.key === `secret_${schema.key}` && s.type === 'dictionary' && s.secret
    )
    const stored = companion ? configuration.inputs?.[companion.key] : undefined
    return stored?.secret && !stored.value ? undefined : companion
}

export function isSecretRowsCompanion(
    schema: CyclotronJobInputSchemaType,
    configuration: SecretRowsConfiguration
): boolean {
    return !!configuration.inputs_schema?.some((s) => findSecretRowsCompanion(s, configuration) === schema)
}

export function dictionaryRowsFromInputs(
    input: CyclotronJobInputType,
    secretInput: CyclotronJobInputType
): DictionaryRow[] {
    return [
        ...Object.entries((input.value ?? {}) as Record<string, unknown>).map(([key, value]) => ({
            key,
            value,
            secret: false,
            masked: false,
        })),
        ...Object.entries((secretInput.value ?? {}) as Record<string, unknown>).map(([key, value]) => ({
            key,
            value,
            secret: true,
            masked: value === MASKED_SECRET_VALUE,
        })),
    ]
}

export function dictionaryRowsToInputs(
    rows: DictionaryRow[],
    initialSecretInput: CyclotronJobInputType
): { value: Record<string, any>; secretInput: CyclotronJobInputType } {
    const filled = rows.filter((r) => r.key.trim() !== '' || typeof r.value !== 'string' || r.value.trim() !== '')
    const value = Object.fromEntries(filled.filter((r) => !r.secret).map((r) => [r.key, r.value]))
    const secrets = filled.filter((r) => r.secret)

    const initialMaskedKeys = Object.entries((initialSecretInput.value ?? {}) as Record<string, unknown>)
        .filter(([, v]) => v === MASKED_SECRET_VALUE)
        .map(([k]) => k)
    const untouched =
        secrets.length > 0 &&
        secrets.every((r) => r.masked) &&
        secrets.map((r) => r.key).join('\n') === initialMaskedKeys.join('\n')

    return {
        value,
        secretInput: untouched
            ? initialSecretInput
            : { value: Object.fromEntries(secrets.map((r) => [r.key, r.value])) },
    }
}
