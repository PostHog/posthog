import { readFileSync } from 'fs'
import path from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { SecretOriginGuard, SecretOriginRefusal, requestOrigin } from './secret-origins'

const ORIGIN_CASES: { url: string; origin: string | null }[] = parseJSON(
    readFileSync(path.resolve(__dirname, '../../../../products/cdp/shared/crosslang/secret_origin_cases.json'), 'utf8')
)

describe('secret origins', () => {
    const SECRET = 'sk_test_origin_0000000000'
    const guard = new SecretOriginGuard({ observeTeams: '', enforceTeams: ' * ' })

    const refusal = (url: string, allowedOrigins: string | string[]): SecretOriginRefusal | null | undefined =>
        guard.check(
            {
                id: 'fn',
                team_id: 1,
                encrypted_inputs: { api_key: { value: SECRET, allowed_origins: allowedOrigins } } as any,
            },
            { url, headers: {}, body: JSON.stringify({ key: SECRET }), params: {} },
            { mayEnforce: true }
        )?.refusal

    it.each(ORIGIN_CASES.filter((c) => c.origin !== null))(
        'resolves $url to the origin Python stores',
        ({ url, origin }) => {
            expect(requestOrigin(url)).toBe(origin)
            expect(refusal(url, [origin!])).toBeNull()
        }
    )
})
