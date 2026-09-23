import { HogFunctionType } from '../types'

// Secret inputs land in `encrypted_inputs` after Django's `move_secret_inputs`
// runs on save; non-secret inputs stay on `inputs`. Request signers resolve
// input-key references at fetch time with the encrypted value first, so a
// secret always wins over a stale plaintext copy.
export function resolveHogFunctionInputValue(
    hogFunction: Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'>,
    key: string
): unknown {
    return hogFunction.encrypted_inputs?.[key]?.value ?? hogFunction.inputs?.[key]?.value
}
