import { readFileSync } from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { HogFunctionType } from '../types'
import { SecretOriginGuard, SecretOriginRefusal, requestOrigin, testedSecretInputs } from './secret-origins'

const ORIGIN_CASES: { url: string; origin: string | null }[] = parseJSON(
    readFileSync(path.resolve(__dirname, '../../../../products/cdp/shared/crosslang/secret_origin_cases.json'), 'utf8')
)

describe('secret origins', () => {
    const SECRET = 'sk_test_origin_0000000000'
    const guard = new SecretOriginGuard({ observeTeams: '', enforceTeams: ' * ' })

    const boundApiKey = (allowedOrigins: string | string[]): HogFunctionType['encrypted_inputs'] => {
        const encryptedInputs = { api_key: { value: SECRET, allowed_origins: allowedOrigins } }
        return encryptedInputs
    }

    const refusal = (url: string, allowedOrigins: string | string[]): SecretOriginRefusal | null =>
        guard.check(
            { id: 'fn', team_id: 1, bytecode: [], encrypted_inputs: boundApiKey(allowedOrigins) },
            { url, headers: {}, body: JSON.stringify({ key: SECRET }), params: {} }
        ).refusal

    it.each<{
        case: string
        hogFunction: Partial<Pick<HogFunctionType, 'inputs_schema' | 'inputs' | 'mappings'>>
        expected: SecretOriginRefusal | null
    }>([
        {
            case: 'refuses it when a top-level secret input saved before encryption',
            hogFunction: {
                inputs_schema: [{ type: 'dictionary', key: 'headers', secret: true }],
                inputs: { headers: { value: { Authorization: SECRET } } },
            },
            expected: { inputKey: 'api_key', origin: 'https://evil.example' },
        },
        {
            case: 'refuses it when a mapping secret input saved before encryption',
            hogFunction: {
                mappings: [
                    {
                        inputs_schema: [{ type: 'dictionary', key: 'headers', secret: true }],
                        inputs: { headers: { value: { Authorization: SECRET } } },
                    },
                ],
            },
            expected: { inputKey: 'api_key', origin: 'https://evil.example' },
        },
        {
            case: 'sends it when a plain dictionary input',
            hogFunction: {
                inputs_schema: [{ type: 'dictionary', key: 'headers' }],
                inputs: { headers: { value: { Authorization: SECRET } } },
            },
            expected: null,
        },
    ])('$case also holds the bound secret', ({ hogFunction, expected }) => {
        const check = guard.check(
            {
                id: 'fn',
                team_id: 1,
                bytecode: [],
                ...hogFunction,
                encrypted_inputs: boundApiKey(['https://good.example']),
            },
            { url: 'https://evil.example/', headers: {}, body: JSON.stringify({ key: SECRET }), params: {} }
        )

        expect(check.refusal).toEqual(expected)
    })

    // JSON.parse, like the API body and the decrypted inputs, keeps `__proto__` as an own key.
    const protoKeyed = (input: object): Record<string, any> => parseJSON(JSON.stringify({ ['__proto__']: input }))

    it.each<{ case: string; inputs: Record<string, any>; encryptedInputs: Record<string, any> }>([
        {
            case: 'the tested configuration',
            inputs: protoKeyed({ value: SECRET, allowed_origins: ['https://good.example'] }),
            encryptedInputs: {},
        },
        {
            case: 'the stored function',
            inputs: {},
            encryptedInputs: protoKeyed({ value: SECRET, allowed_origins: ['https://good.example'] }),
        },
    ])('refuses a test send of a secret keyed __proto__ from $case', ({ inputs, encryptedInputs }) => {
        const tested = testedSecretInputs({
            inputs_schema: [{ type: 'string', key: '__proto__', secret: true }],
            inputs,
            encrypted_inputs: encryptedInputs,
        })

        const check = guard.check(
            { id: 'fn', team_id: 1, bytecode: [], encrypted_inputs: tested },
            { url: 'https://evil.example/', headers: {}, body: JSON.stringify({ key: SECRET }), params: {} }
        )

        expect(check.refusal).toEqual({ inputKey: '__proto__', origin: 'https://evil.example' })
    })

    it.each(ORIGIN_CASES.filter((c) => c.origin !== null))(
        'resolves $url to the origin Python stores',
        ({ url, origin }) => {
            expect(requestOrigin(url)).toBe(origin)
            expect(refusal(url, [origin!])).toBeNull()
        }
    )
})
