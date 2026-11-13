import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '~/cdp/types'
import { logger } from '~/common/utils/logger'

import { collectTemplateReferences } from './hogflow-variable-usage'

const PERSON_PROPERTY_REGEXES = [
    /\bperson\.properties\.([A-Za-z_$][A-Za-z0-9_$]*)/g,
    /\bperson\.properties\s*\[\s*['"]([^'"\]]+)['"]\s*\]/g,
]

// Operation.STRING and Operation.GET_GLOBAL from @posthog/hogvm, which is a const enum and can't be
// imported under isolatedModules
const STRING = 32
const GET_GLOBAL = 1

export function personPropertiesInTemplates(config: { inputs?: unknown; mappings?: unknown }): string[] {
    const referenced = new Set<string>()
    collectTemplateReferences(config.inputs, PERSON_PROPERTY_REGEXES, referenced)
    collectTemplateReferences(config.mappings, PERSON_PROPERTY_REGEXES, referenced)
    return [...referenced]
}

/** Matches the chain encoding [STRING, key, STRING, 'properties', STRING, 'person', GET_GLOBAL, length]. */
export function personPropertiesInBytecode(bytecode: unknown): string[] {
    if (!Array.isArray(bytecode)) {
        return []
    }
    const referenced = new Set<string>()
    bytecode.forEach((op, index) => {
        const key = bytecode[index - 2]
        if (
            op === 'properties' &&
            bytecode[index - 1] === STRING &&
            bytecode[index + 1] === STRING &&
            bytecode[index + 2] === 'person' &&
            bytecode[index + 3] === GET_GLOBAL &&
            bytecode[index - 3] === STRING &&
            typeof key === 'string'
        ) {
            referenced.add(key)
        }
    })
    return [...referenced]
}

/** The dequeue's person comes from the replica, which can lack a property the leader already has. */
export async function loadMissingPersonProperties(
    invocation: CyclotronJobInvocationHogFlow,
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
    referenced: () => string[]
): Promise<void> {
    const properties = invocation.person?.properties
    if (!invocation.loadPersonProperties || !properties) {
        return
    }
    const missing = referenced().filter((key) => !(key in properties))
    if (missing.length === 0) {
        return
    }

    const loaded = await invocation.loadPersonProperties(missing).catch((error) => {
        logger.warn('[HogFlowPersonPropertyUsage] Could not load missing person properties', {
            teamId: invocation.teamId,
            hogFlowId: invocation.hogFlow.id,
            error: String(error),
        })
        return undefined
    })
    if (loaded?.person) {
        invocation.person = loaded.person
        invocation.filterGlobals = loaded.filterGlobals
        // The result carries a shallow clone, so it needs the same person.
        result.invocation.person = loaded.person
        result.invocation.filterGlobals = loaded.filterGlobals
    }
}
