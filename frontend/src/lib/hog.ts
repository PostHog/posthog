import { exec as hogExec, ExecOptions, ExecResult, VMState } from '@posthog/hogvm'

export function exec(code: any[] | VMState, options?: ExecOptions): ExecResult {
    return hogExec(code, { external: {}, ...(options ?? {}) })
}
