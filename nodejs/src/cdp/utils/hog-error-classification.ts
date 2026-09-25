import { HogVMErrorKind, HogVMException } from '@posthog/hogvm'

/**
 * Who has to act on a failed filter or input.
 *
 * - `data`: the program fits the runtime and this event did not fit the program. Another event may
 *   pass, so nothing is broken and nobody needs to act.
 * - `legacy`: the program asks the runtime for something it does not have, and was saved before the
 *   compiler checked that. The owner has to fix the function; replaying the event cannot.
 * - `drift`: the same, but the program was compiled against an older runtime, so a change on our side
 *   broke it. Replay after the runtime or the compiler is fixed.
 * - `bug`: the same, but compiled against this runtime, so the compiler and the VM disagree about
 *   what exists. Ours to fix.
 * - `limit`: the program ran out of time, memory or stack. Replay would run out again, so it is the
 *   owner's to fix. Many functions hitting it at once is a different story, and the label shows that.
 * - `platform`: a JavaScript error the VM let through, or something that is not an error at all.
 *   Ours to look at.
 */
export type HogErrorClass = 'data' | 'legacy' | 'drift' | 'bug' | 'limit' | 'platform'

export type HogErrorContract = {
    /** The stamp on the bytecode that ran, from `filters.bytecode_contract`. Absent on older bytecode. */
    bytecodeContract?: string
    /** The stamp of the runtime that ran it, from `currentRuntimeContractHash()`. */
    runtimeContract: string
}

type KindedError = { kind: HogVMErrorKind }

const KINDS: ReadonlySet<string> = new Set<HogVMErrorKind>(['contract', 'data', 'limit'])

export const isHogVMErrorKind = (value: unknown): value is HogVMErrorKind =>
    typeof value === 'string' && KINDS.has(value)

// By shape rather than instanceof: the error can come from another realm or an older build of the VM.
const isHogVMException = (error: object): error is KindedError =>
    error instanceof HogVMException || isHogVMErrorKind((error as Partial<KindedError>).kind)

/**
 * The first VM error in the cause chain. Callers wrap the VM's error to add the field or the
 * function it happened in, and the wrapper carries no kind of its own.
 */
function findHogVMException(error: unknown): KindedError | undefined {
    let current: unknown = error
    for (let depth = 0; depth < 10 && typeof current === 'object' && current !== null; depth++) {
        if (isHogVMException(current)) {
            return current
        }
        current = (current as { cause?: unknown }).cause
    }
    return undefined
}

export function classifyHogError(error: unknown, contract: HogErrorContract): HogErrorClass {
    const vmError = findHogVMException(error)
    if (!vmError) {
        return 'platform'
    }
    switch (vmError.kind) {
        case 'data':
            return 'data'
        case 'limit':
            return 'limit'
        case 'contract':
            if (!contract.bytecodeContract) {
                return 'legacy'
            }
            return contract.bytecodeContract === contract.runtimeContract ? 'bug' : 'drift'
    }
}
