import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

import {
    MASKED_SECRET_VALUE,
    SecretDictionaryRow,
    canAddSecretRow,
    findSecretRowsCompanion,
    secretRowsFromInput,
    secretRowsToValue,
} from './dictionarySecretRows'

const STORED: CyclotronJobInputType = {
    secret: true,
    value: { Authorization: MASKED_SECRET_VALUE, 'X-Api-Key': MASKED_SECRET_VALUE },
}

describe('dictionarySecretRows', () => {
    it.each<[string, (rows: SecretDictionaryRow[]) => SecretDictionaryRow[], Record<string, string>]>([
        ['sends the mask for every untouched entry', (rows) => rows, STORED.value],
        [
            'sends the mask for entries left hidden next to a replaced one',
            (rows) => rows.map((r) => (r.key === 'Authorization' ? { ...r, value: 'Bearer new', masked: false } : r)),
            { Authorization: 'Bearer new', 'X-Api-Key': MASKED_SECRET_VALUE },
        ],
        [
            'drops a deleted entry',
            (rows) => rows.filter((r) => r.key !== 'Authorization'),
            { 'X-Api-Key': MASKED_SECRET_VALUE },
        ],
        [
            'keeps the stored value for an entry opened with Replace but left empty',
            (rows) => rows.map((r) => ({ ...r, masked: false })),
            STORED.value,
        ],
        [
            'ignores empty rows',
            (rows) => [...rows, { key: ' ', value: '', masked: false, stored: false }],
            STORED.value,
        ],
    ])('%s', (_name, edit, expected) => {
        expect(secretRowsToValue(edit(secretRowsFromInput(STORED)))).toEqual(expected)
    })

    it.each<[string, CyclotronJobInputType | undefined, boolean]>([
        ['a new function', undefined, true],
        ['a stored secret with its keys', STORED, true],
        ['a stored secret without its keys', { secret: true, value: undefined }, false],
    ])('allows adding a secret row for %s', (_name, stored, allowed) => {
        expect(canAddSecretRow(stored)).toBe(allowed)
    })

    const HEADERS = { key: 'headers', type: 'dictionary', label: 'Headers' } as CyclotronJobInputSchemaType
    const SECRET_HEADERS = {
        key: 'secret_headers',
        type: 'dictionary',
        label: 'Secret headers',
        secret: true,
    } as CyclotronJobInputSchemaType

    it.each<[string, CyclotronJobInputSchemaType[], boolean]>([
        ['a secret companion input', [HEADERS, SECRET_HEADERS], true],
        ['no secret companion input', [HEADERS], false],
    ])('pairs the secret rows input for %s', (_name, inputsSchema, paired) => {
        expect(findSecretRowsCompanion(HEADERS, inputsSchema)).toBe(paired ? SECRET_HEADERS : undefined)
    })
})
