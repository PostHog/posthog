import { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

import {
    DictionaryRow,
    MASKED_SECRET_VALUE,
    dictionaryRowsFromInputs,
    dictionaryRowsToInputs,
    findSecretRowsCompanion,
    isSecretRowsCompanion,
} from './dictionarySecretRows'

const STORED: CyclotronJobInputType = {
    secret: true,
    value: { Authorization: MASKED_SECRET_VALUE, 'X-Api-Key': MASKED_SECRET_VALUE },
}

describe('dictionarySecretRows', () => {
    it.each<[string, (rows: DictionaryRow[]) => DictionaryRow[], CyclotronJobInputType, CyclotronJobInputType]>([
        ['keeps an untouched stored secret as sent', (rows) => rows, STORED, STORED],
        [
            'sends the mask for entries left hidden next to a replaced one',
            (rows) => rows.map((r) => (r.key === 'Authorization' ? { ...r, value: 'Bearer new', masked: false } : r)),
            STORED,
            { value: { Authorization: 'Bearer new', 'X-Api-Key': MASKED_SECRET_VALUE } },
        ],
        [
            'drops a deleted secret row',
            (rows) => rows.filter((r) => r.key !== 'Authorization'),
            STORED,
            { value: { 'X-Api-Key': MASKED_SECRET_VALUE } },
        ],
        [
            'clears the secret when every secret row is deleted',
            (rows) => rows.filter((r) => !r.secret),
            STORED,
            { value: {} },
        ],
        [
            'moves a locked row into the secret input',
            (rows) => rows.map((r) => (r.key === 'Content-Type' ? { ...r, secret: true } : r)),
            STORED,
            {
                value: {
                    'Content-Type': 'application/json',
                    Authorization: MASKED_SECRET_VALUE,
                    'X-Api-Key': MASKED_SECRET_VALUE,
                },
            },
        ],
        [
            'ignores empty rows',
            (rows) => [...rows, { key: ' ', value: '', secret: true, masked: false }],
            STORED,
            STORED,
        ],
    ])('%s', (_name, edit, initialSecret, expectedSecret) => {
        const rows = edit(dictionaryRowsFromInputs({ value: { 'Content-Type': 'application/json' } }, initialSecret))
        expect(dictionaryRowsToInputs(rows, initialSecret).secretInput).toEqual(expectedSecret)
    })

    it('keeps plain rows out of the secret input', () => {
        expect(
            dictionaryRowsToInputs(
                dictionaryRowsFromInputs({ value: { 'Content-Type': 'application/json' } }, STORED),
                STORED
            ).value
        ).toEqual({ 'Content-Type': 'application/json' })
    })

    const HEADERS = { key: 'headers', type: 'dictionary', label: 'Headers' } as CyclotronJobInputSchemaType
    const SECRET_HEADERS = {
        key: 'secret_headers',
        type: 'dictionary',
        label: 'Secret headers',
        secret: true,
    } as CyclotronJobInputSchemaType

    it.each<[string, CyclotronJobInputSchemaType[], CyclotronJobInputType | undefined, boolean]>([
        ['a new function', [HEADERS, SECRET_HEADERS], undefined, true],
        ['a stored secret with its keys', [HEADERS, SECRET_HEADERS], STORED, true],
        ['a stored secret without its keys', [HEADERS, SECRET_HEADERS], { secret: true, value: undefined }, false],
        ['no secret companion input', [HEADERS], undefined, false],
    ])('pairs the secret rows input for %s', (_name, inputs_schema, stored, paired) => {
        const inputs: Record<string, CyclotronJobInputType> = stored ? { secret_headers: stored } : {}
        const configuration = { inputs_schema, inputs }
        expect(findSecretRowsCompanion(HEADERS, configuration)).toBe(paired ? SECRET_HEADERS : undefined)
        expect(isSecretRowsCompanion(SECRET_HEADERS, configuration)).toBe(paired)
    })
})
