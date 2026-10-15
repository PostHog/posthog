// Match the context limits of the workflow AI endpoints (validate_workflow_context in workflow_classifications.py),
// so a mocked test run fails on the same inputs as a live run.
const MAX_CONTEXT_CHARS = 65_536
const MAX_CONTEXT_DEPTH = 100

const nestingExceeds = (value: unknown, limit: number): boolean => {
    const pending: [unknown, number][] = [[value, 1]]
    while (pending.length > 0) {
        const [item, depth] = pending.pop()!
        if (item === null || typeof item !== 'object') {
            continue
        }
        if (depth > limit) {
            return true
        }
        for (const child of Object.values(item)) {
            pending.push([child, depth + 1])
        }
    }
    return false
}

export const assertWorkflowContextFits = (context: unknown): void => {
    if (nestingExceeds(context, MAX_CONTEXT_DEPTH)) {
        throw new Error(`Keep the context to ${MAX_CONTEXT_DEPTH} levels of nesting or fewer`)
    }
    if ([...(JSON.stringify(context) ?? '')].length > MAX_CONTEXT_CHARS) {
        throw new Error(`Keep the context to ${MAX_CONTEXT_CHARS} characters of JSON or fewer`)
    }
}
