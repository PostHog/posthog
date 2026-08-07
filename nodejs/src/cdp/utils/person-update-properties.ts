import { Counter } from 'prom-client'

import { operations } from '@posthog/hogvm'

import { HogBytecode, HogFunctionType } from '../types'

/**
 * Stored events are losing the duplicated person update payload, so `properties.$set` and
 * `properties.$set_once` will not be there to read. Hog functions read them from filters, from
 * templated inputs and from function bodies, and we have no idea how much of that is load bearing.
 *
 * This measures it, and it measures the fix at the same time. For every read a function makes, it
 * asks the question the migration turns on: could the event's person snapshot have served this
 * value instead? So the counter reports both how often these reads happen and how many of them a
 * polyfill would carry, before any polyfill exists.
 *
 * A read of `properties.$set.email` is mappable when the person snapshot holds the same value under
 * `email`. A whole-object read of `properties.$set` is not mappable by key at all, because the
 * snapshot is the person's whole state rather than the subset one event updated. `$set_once` is
 * expected to disagree sometimes: the person keeps the value it was first given, not the one a
 * later event attempted.
 */
export const PERSON_UPDATE_PROPERTY_KEYS = ['$set', '$set_once'] as const

export type PersonUpdatePropertyKey = (typeof PERSON_UPDATE_PROPERTY_KEYS)[number]

/** Where in a hog function the read comes from. */
export type PersonUpdatePropertyReadSource = 'filters' | 'inputs' | 'hog' | 'legacy_plugin'

export type PersonUpdatePropertyRead = {
    key: PersonUpdatePropertyKey
    /** The chain after the key. Empty for a whole-object read. */
    path: string[]
}

/** Whether the person snapshot could have stood in for one read. */
export type PersonUpdatePropertyOutcome =
    /** The snapshot holds the same value. A polyfill would be transparent. */
    | 'mappable'
    /** The snapshot holds a different value. A polyfill would change what the function sees. */
    | 'value_differs'
    /** The event set this key but the snapshot does not have it. A polyfill would resolve nothing. */
    | 'missing_on_person'
    /** The event carried no such value, so the read already resolves to nothing. */
    | 'absent_in_event'
    /** The event has no person, so there is nothing to map onto. */
    | 'no_person'
    /** A whole-object read, which no per-key mapping covers. */
    | 'whole_object'

const personUpdatePropertyReads = new Counter({
    name: 'cdp_person_update_property_read',
    help: 'Reads of $set or $set_once from event properties, by whether the person snapshot could have served them',
    labelNames: ['key', 'source', 'function_type', 'outcome'],
})

const personUpdatePropertyErrors = new Counter({
    name: 'cdp_person_update_property_error',
    help: 'Failures inside the $set / $set_once read tracking, which is observation-only and never fails an invocation',
    labelNames: ['stage'],
})

/**
 * Nothing in this module may throw.
 *
 * It is observation only, but it runs inside the filter and executor paths, where the surrounding
 * error handling means very different things: a throw during filtering is read as "this event does
 * not match", which would silently stop a destination firing, and a throw in the executor fails the
 * invocation. Neither is an acceptable outcome for a counter, so every entry point returns a
 * fallback and reports the failure through `cdp_person_update_property_error` instead.
 */
function guarded<T>(stage: string, fallback: T, fn: () => T): T {
    try {
        return fn()
    } catch {
        personUpdatePropertyErrors.inc({ stage })
        return fallback
    }
}

// Bounds the walk over a compiled input tree. Inputs come from parsed JSON so they cannot be
// cyclic, but a cap keeps a pathological shape from exhausting the stack.
const MAX_INPUT_DEPTH = 32

// Read off the VM's own opcode table so the scanner cannot drift from the compiler.
const OP_GET_GLOBAL = operations.indexOf('GET_GLOBAL')
const OP_STRING = operations.indexOf('STRING')

const UPDATE_PROPERTY_KEYS = new Set<string>(PERSON_UPDATE_PROPERTY_KEYS)

// Globals whose `properties` are the event's own. Person and group properties have a `$set` of
// their own meaning and are not part of the payload being removed.
const EVENT_PROPERTY_ROOTS = new Set(['event', 'properties'])

function isPersonUpdatePropertyKey(value: unknown): value is PersonUpdatePropertyKey {
    return typeof value === 'string' && UPDATE_PROPERTY_KEYS.has(value)
}

/**
 * Recover the field chain behind a `GET_GLOBAL` op. The compiler emits the chain as `STRING`/value
 * pairs in reverse order directly ahead of the op, then the op and the chain length — so
 * `event.properties.$set.email` compiles to one `GET_GLOBAL 4` rather than a run of `GET_PROPERTY`.
 */
function readGlobalChain(bytecode: HogBytecode, opIndex: number): string[] | null {
    const chainLength = bytecode[opIndex + 1]
    if (typeof chainLength !== 'number' || chainLength < 2) {
        return null
    }

    const chain: string[] = []
    for (let position = 0; position < chainLength; position++) {
        const stringOpIndex = opIndex - 2 * (position + 1)
        if (stringOpIndex < 0 || bytecode[stringOpIndex] !== OP_STRING) {
            return null
        }
        // Array indexes come through the same opcode, e.g. `properties.$set[1]`.
        const segment = bytecode[stringOpIndex + 1]
        if (typeof segment !== 'string' && typeof segment !== 'number') {
            return null
        }
        chain.push(String(segment))
    }
    return chain
}

/**
 * Find the reads of `$set` / `$set_once` off an event's properties in one compiled chunk.
 *
 * Only globals compile to a single chain, so a body that assigns `let props := event.properties` and
 * then reads `props.$set.email` becomes `GET_PROPERTY` hops and is not found here. Those reads are
 * invisible to any static pass, which is worth knowing when reading the counter as a total.
 */
export function findPersonUpdatePropertyReads(bytecode: unknown): PersonUpdatePropertyRead[] {
    if (!Array.isArray(bytecode)) {
        return []
    }
    return guarded('find_reads', [], () => scanForPersonUpdatePropertyReads(bytecode))
}

function scanForPersonUpdatePropertyReads(bytecode: HogBytecode): PersonUpdatePropertyRead[] {
    const reads: PersonUpdatePropertyRead[] = []

    for (let index = 0; index < bytecode.length; index++) {
        if (bytecode[index] !== OP_GET_GLOBAL) {
            continue
        }
        const chain = readGlobalChain(bytecode, index)
        if (!chain || !EVENT_PROPERTY_ROOTS.has(chain[0])) {
            continue
        }

        // Destination globals are rooted at `event.properties`, filter globals at `properties`.
        const keyIndex = chain.findIndex(
            (segment, position) =>
                position > 0 && chain[position - 1] === 'properties' && isPersonUpdatePropertyKey(segment)
        )
        if (keyIndex === -1) {
            continue
        }

        reads.push({ key: chain[keyIndex] as PersonUpdatePropertyKey, path: chain.slice(keyIndex + 1) })
    }

    return dedupeReads(reads)
}

function dedupeReads(reads: PersonUpdatePropertyRead[]): PersonUpdatePropertyRead[] {
    return [...new Map(reads.map((read) => [`${read.key}.${read.path.join('.')}`, read])).values()]
}

const readsByBytecode = new WeakMap<object, PersonUpdatePropertyRead[]>()

/** The reads compiled into one chunk of bytecode — a filter, or a function body. */
export function bytecodePersonUpdatePropertyReads(bytecode: unknown): PersonUpdatePropertyRead[] {
    if (!Array.isArray(bytecode)) {
        return []
    }
    let reads = readsByBytecode.get(bytecode)
    if (!reads) {
        reads = findPersonUpdatePropertyReads(bytecode)
        readsByBytecode.set(bytecode, reads)
    }
    return reads
}

/** Compiled input values are trees of nested objects with bytecode arrays at the leaves. */
function collectInputBytecode(value: unknown, found: HogBytecode[], depth = 0): void {
    if (depth > MAX_INPUT_DEPTH) {
        return
    }
    if (Array.isArray(value)) {
        if (value[0] === '_h' || value[0] === '_H') {
            found.push(value)
            return
        }
        value.forEach((item) => collectInputBytecode(item, found, depth + 1))
        return
    }
    if (typeof value === 'object' && value !== null) {
        Object.values(value).forEach((item) => collectInputBytecode(item, found, depth + 1))
    }
}

const readsByHogFunction = new WeakMap<HogFunctionType, PersonUpdatePropertyRead[]>()

/** The reads compiled into one function's templated inputs, including its mappings' inputs. */
export function inputsPersonUpdatePropertyReads(hogFunction: HogFunctionType): PersonUpdatePropertyRead[] {
    const cached = readsByHogFunction.get(hogFunction)
    if (cached) {
        return cached
    }

    // A failure caches its empty result too, so a function whose config breaks the walk costs this
    // once rather than on every invocation.
    const reads = guarded('inputs_reads', [], () => {
        const inputBytecode: HogBytecode[] = []
        for (const inputs of [
            hogFunction.inputs,
            hogFunction.encrypted_inputs,
            ...(hogFunction.mappings ?? []).map((mapping) => mapping.inputs),
        ]) {
            for (const input of Object.values(inputs ?? {})) {
                collectInputBytecode(input?.bytecode, inputBytecode)
            }
        }
        return dedupeReads(inputBytecode.flatMap((bytecode) => findPersonUpdatePropertyReads(bytecode)))
    })
    readsByHogFunction.set(hogFunction, reads)
    return reads
}

/** A legacy plugin is handed both payloads whole, so it reads them on every invocation. */
export const LEGACY_PLUGIN_PERSON_UPDATE_PROPERTY_READS: PersonUpdatePropertyRead[] = PERSON_UPDATE_PROPERTY_KEYS.map(
    (key) => ({ key, path: [] })
)

function resolvePath(root: unknown, path: string[]): unknown {
    let value = root
    for (const segment of path) {
        if (typeof value !== 'object' || value === null) {
            return undefined
        }
        value = (value as Record<string, unknown>)[segment]
    }
    return value
}

function sameValue(left: unknown, right: unknown): boolean {
    if (left === right) {
        return true
    }
    if (typeof left !== 'object' || typeof right !== 'object' || left === null || right === null) {
        return false
    }
    // Person and event properties come from parsed JSON, but a throwing getter or a cyclic value
    // reaching here should read as "not the same" rather than take the invocation down.
    return guarded('compare', false, () => JSON.stringify(left) === JSON.stringify(right))
}

/** The question the migration turns on: could this read have come off the person snapshot? */
export function personUpdatePropertyReadOutcome(
    read: PersonUpdatePropertyRead,
    eventProperties: Record<string, any> | undefined,
    personProperties: Record<string, any> | undefined
): PersonUpdatePropertyOutcome {
    if (read.path.length === 0) {
        return 'whole_object'
    }
    const eventValue = resolvePath(eventProperties?.[read.key], read.path)
    if (eventValue === undefined) {
        return 'absent_in_event'
    }
    if (!personProperties) {
        return 'no_person'
    }
    const personValue = resolvePath(personProperties, read.path)
    if (personValue === undefined) {
        return 'missing_on_person'
    }
    return sameValue(eventValue, personValue) ? 'mappable' : 'value_differs'
}

/**
 * Count one surface's reads against the globals it ran with.
 *
 * Called per invocation, so it stays on the memoized read list and only walks the globals for the
 * functions that actually reference these properties.
 */
export function trackPersonUpdatePropertyReads(options: {
    reads: PersonUpdatePropertyRead[]
    source: PersonUpdatePropertyReadSource
    functionType: string
    eventProperties: Record<string, any> | undefined
    personProperties: Record<string, any> | undefined
}): void {
    const { reads, source, functionType, eventProperties, personProperties } = options
    if (reads.length === 0) {
        return
    }

    // Guarded per read, so one hostile property does not cost the other reads their count.
    for (const read of reads) {
        guarded('track', undefined, () => {
            personUpdatePropertyReads.inc({
                key: read.key,
                source,
                function_type: functionType,
                outcome: personUpdatePropertyReadOutcome(read, eventProperties, personProperties),
            })
        })
    }
}

/**
 * The polyfill. Off unless `CDP_PERSON_UPDATE_PROPERTY_POLYFILL_BEFORE` is set to a date.
 *
 * Functions created before that date keep working: the reads they make are filled in from the
 * person snapshot. Functions created on or after it never see these properties at all, even while
 * stored events still carry them, so the deprecation is real for anything new rather than a grace
 * period that never ends. `CDP_PERSON_UPDATE_PROPERTY_POLYFILL_EXCLUDED_TEAMS` opts a team out of
 * both behaviours.
 */
export type PersonUpdatePropertyPolyfillMode =
    /** Fill in the reads this function makes from the person snapshot. */
    | 'map'
    /** Resolve nothing, whatever the stored event carries. */
    | 'hide'
    /** Leave the event exactly as it arrived. */
    | 'off'

let excludedTeamsSource: string | undefined
let excludedTeams = new Set<number>()

function isExcludedTeam(teamId: number): boolean {
    const source = process.env.CDP_PERSON_UPDATE_PROPERTY_POLYFILL_EXCLUDED_TEAMS ?? ''
    if (source !== excludedTeamsSource) {
        excludedTeamsSource = source
        excludedTeams = new Set(
            source
                .split(',')
                .map((id) => parseInt(id.trim(), 10))
                .filter((id) => !isNaN(id))
        )
    }
    return excludedTeams.has(teamId)
}

/**
 * A hog flow carries no creation date, so the date rule cannot classify one and it is left alone.
 * Its filters are still counted.
 */
export function personUpdatePropertyPolyfillMode(fn: {
    team_id: number
    created_at?: string
}): PersonUpdatePropertyPolyfillMode {
    // 'off' is the fallback for anything unexpected, so a failure leaves the event as it arrived.
    return guarded('polyfill_mode', 'off', () => {
        const before = process.env.CDP_PERSON_UPDATE_PROPERTY_POLYFILL_BEFORE
        if (!before || !fn.created_at || isExcludedTeam(fn.team_id)) {
            return 'off'
        }
        const cutoff = Date.parse(before)
        const createdAt = Date.parse(fn.created_at)
        if (isNaN(cutoff) || isNaN(createdAt)) {
            return 'off'
        }
        return createdAt < cutoff ? 'map' : 'hide'
    })
}

function setPath(root: Record<string, any>, path: string[], value: unknown): void {
    let target = root
    for (const segment of path.slice(0, -1)) {
        const next = target[segment]
        target[segment] = typeof next === 'object' && next !== null ? { ...next } : {}
        target = target[segment]
    }
    target[path[path.length - 1]] = value
}

/**
 * Build the event properties one function should run against, or nothing when they are unchanged.
 *
 * A `map` fills in only the paths the function reads, so a function that reads
 * `properties.$set.email` gets that one key and nothing else. Substituting the whole snapshot would
 * hand it every property the person has, which is not what the event updated. Filling nothing
 * leaves the key absent rather than present and empty, so a filter on whether it is set still reads
 * the way it will once storage drops the payload.
 */
export function polyfilledEventProperties(options: {
    mode: PersonUpdatePropertyPolyfillMode
    reads: PersonUpdatePropertyRead[]
    eventProperties: Record<string, any> | undefined
    personProperties: Record<string, any> | undefined
}): Record<string, any> | undefined {
    const { mode, reads, eventProperties, personProperties } = options
    if (mode === 'off' || typeof eventProperties !== 'object' || eventProperties === null) {
        return undefined
    }
    // Returning nothing leaves the event as it arrived, which is the safe outcome for a failure.
    return guarded('polyfill', undefined, () =>
        buildPolyfilledEventProperties(mode, reads, eventProperties, personProperties)
    )
}

function buildPolyfilledEventProperties(
    mode: PersonUpdatePropertyPolyfillMode,
    reads: PersonUpdatePropertyRead[],
    eventProperties: Record<string, any>,
    personProperties: Record<string, any> | undefined
): Record<string, any> | undefined {
    if (mode === 'hide') {
        const present = PERSON_UPDATE_PROPERTY_KEYS.filter((key) =>
            Object.prototype.hasOwnProperty.call(eventProperties, key)
        )
        if (present.length === 0) {
            return undefined
        }
        const hidden = { ...eventProperties }
        present.forEach((key) => delete hidden[key])
        return hidden
    }

    if (reads.length === 0 || !personProperties) {
        return undefined
    }

    let mapped: Record<string, any> | undefined
    for (const read of reads) {
        if (read.path.length === 0) {
            // A whole-object read has no per-key answer, so it keeps whatever the event carried.
            continue
        }
        if (resolvePath(eventProperties[read.key], read.path) !== undefined) {
            continue
        }
        const personValue = resolvePath(personProperties, read.path)
        if (personValue === undefined) {
            continue
        }
        mapped ??= { ...eventProperties }
        const payload = mapped[read.key]
        mapped[read.key] = typeof payload === 'object' && payload !== null ? { ...payload } : {}
        setPath(mapped[read.key], read.path, personValue)
    }
    return mapped
}

/**
 * Resolve one payload for a legacy plugin, which reads it whole from JavaScript.
 *
 * There is no per-key answer to give a consumer that enumerates the object, so a mapped plugin gets
 * the person snapshot itself. That is broader than the subset one event updated, and it is the only
 * substitute that works for a plugin syncing traits. A copy goes over so a plugin mutating it does
 * not reach the snapshot the rest of the invocation reads.
 */
export function resolveLegacyPluginPersonUpdatePayload(
    mode: PersonUpdatePropertyPolyfillMode,
    key: PersonUpdatePropertyKey,
    eventProperties: Record<string, any> | undefined,
    personProperties: Record<string, any> | undefined
): Record<string, any> | undefined {
    // Falling back to the raw payload keeps a failure from changing what the plugin receives.
    return guarded('legacy_payload', eventProperties?.[key], () => {
        if (mode === 'hide') {
            return undefined
        }
        const raw = eventProperties?.[key]
        if (raw !== undefined || mode === 'off' || !personProperties) {
            return raw
        }
        return { ...personProperties }
    })
}
