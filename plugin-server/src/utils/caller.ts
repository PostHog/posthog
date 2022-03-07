// Utils for determining the caller of a function
// Largely inspired in https://github.com/sindresorhus/caller-path

const DEFAULT_FILES_TO_IGNORE = ['caller', 'status']

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
    for (const cal of errorStack || []) {
        console.log(cal.getFileName())
    }
    const stack = errorStack ? errorStack.slice(1) : []
    return stack
}

export function callerCallsite(depth = 0, filesToIgnore = DEFAULT_FILES_TO_IGNORE): CallSite | undefined {
    const callers = []
    const callerFileSet = new Set()

    for (const callsite of callsites() || []) {
        const fileName = callsite.getFileName()
        const hasReceiver =
            fileName !== null && !filesToIgnore.some((f) => fileName.replaceAll(/\.[jt]sx?$/g, '').endsWith(f))

        if (!callerFileSet.has(fileName)) {
            callerFileSet.add(fileName)
            callers.unshift(callsite)
        }
        console.log(callsite.getTypeName(), callsite.getFileName(), callers)

        if (hasReceiver) {
            return callers[depth]
        }
    }
}

export function callerPath(): string {
    const callsite = callerCallsite()
    return callsite ? callsite.getFileName() : 'unknown location'
}
