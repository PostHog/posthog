import { exec as hogExec, ExecOptions, ExecResult, VMState } from '@posthog/hogvm'
import * as crypto from 'crypto'

export function execHog(code: any[] | VMState, options?: ExecOptions): ExecResult {
    return hogExec(code, {
        external: {
            crypto, // TODO: switch to webcrypto and polyfill on the node side
            re2: undefined,
        },
        ...(options ?? {}),
    })
}
