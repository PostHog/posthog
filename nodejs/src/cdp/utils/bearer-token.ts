import { HogFunctionType } from '../types'
import { resolveHogFunctionInputValue } from './hog-function-inputs'

export function resolveBearerToken(
    url: string,
    inputKey: string,
    hogFunction: Pick<HogFunctionType, 'inputs' | 'encrypted_inputs' | 'inputs_schema'>
): { ok: true; token: string } | { ok: false; error: string } {
    const schema = hogFunction.inputs_schema?.find((input) => input.key === inputKey)
    const token = resolveHogFunctionInputValue(hogFunction, inputKey)
    if (!schema?.secret || typeof token !== 'string' || !token.trim() || /[\r\n]/.test(token)) {
        return { ok: false, error: 'The API key is missing or invalid. Set the secret API key input, then retry.' }
    }
    if (!URL.canParse(url) || new URL(url).protocol !== 'https:') {
        return { ok: false, error: 'API key authentication requires HTTPS. Update the request URL, then retry.' }
    }
    return { ok: true, token }
}
