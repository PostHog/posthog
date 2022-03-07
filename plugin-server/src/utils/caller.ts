// Utils for determining the caller of a function
// Largely inspired in https://github.com/sindresorhus/caller-path

interface CallSite {
    getThis(): any
    getTypeName(): string
    getFunctionName(): string
    getMethodName(): string
    getFileName(): string
    getLineNumber(): number
    getColumnNumber(): number
    getFunction(): () => any
    getEvalOrigin(): string
    isNative(): boolean
    isToplevel(): boolean
    isEval(): boolean
    isConstructor(): boolean
}

export function callsites(): CallSite[] {
    const _prepareStackTrace = Error.prepareStackTrace
    Error.prepareStackTrace = (_, stack) => stack
    const errorStack: CallSite[] | undefined = new Error().stack as any
    Error.prepareStackTrace = _prepareStackTrace
    const stack = errorStack ? errorStack.slice(1) : []
    return stack
}

export function callerCallsite(depth = 0): CallSite | undefined {
    const callers = []
    const callerFileSet = new Set()

    for (const callsite of callsites() || []) {
        const fileName = callsite.getFileName()
        const hasReceiver = callsite.getTypeName() !== null && fileName !== null

        if (!callerFileSet.has(fileName)) {
            callerFileSet.add(fileName)
            callers.unshift(callsite)
        }

        if (hasReceiver) {
            return callers[depth]
        }
    }
}

export function callerpath(): string {
    const callsite = callerCallsite()
    return callsite ? callsite.getFileName() : 'unknown location'
}
