import { ASYNC_STL, BYTECODE_STL, STL } from '@posthog/hogvm'

import { ClickHouseTimestamp, ProjectId, RawClickHouseEvent } from '../../types'
import { HogFunctionInvocationGlobals, HogFunctionInvocationGlobalsWithInputs } from '../types'
import { convertClickhouseRawEventToFilterGlobals, convertToHogFunctionFilterGlobal } from './hog-function-filtering'

/** Where Django reads the result. Relative to the repository root. */
export const FILTER_GLOBALS_RELATIVE_PATH = 'posthog/cdp/filter_globals.json'

export type FilterRuntime = {
    /** Data globals every filter compiled by compile_filters_bytecode is evaluated with. */
    roots: string[]
    /** Standard-library names the VM hands back as values and can then invoke, so a filter can pass
     * them as callbacks. */
    callables: string[]
    /**
     * Every standard-library name a filter can call directly, the bytecode-implemented ones included, with
     * the argument count the VM enforces as [min, max]. A null max means unbounded.
     */
    functions: Record<string, [number, number | null]>
    /** Root names an input template can read: the union of what every invocation path puts in globals. */
    template_roots: string[]
}

// A key added to HogFunctionInvocationGlobals has to be added here or the build fails.
const templateRoots: Record<keyof HogFunctionInvocationGlobalsWithInputs, true> = {
    project: true,
    source: true,
    event: true,
    person: true,
    groups: true,
    request: true,
    unsubscribe_url: true,
    unsubscribe_url_one_click: true,
    actions: true,
    variables: true,
    inputs: true,
}

// These stand for the callers of compile_filters_bytecode: hog function filters, evaluated by the two
// builders below. A new caller with a different globals shape has to be added here, or Django will
// validate against the wrong set. Every input is populated so a builder that only sets a key when its
// input is present still sets it.
const invocationGlobals: Pick<HogFunctionInvocationGlobals, 'event' | 'person' | 'groups' | 'variables'> = {
    event: {
        uuid: '00000000-0000-0000-0000-000000000001',
        event: '$pageview',
        distinct_id: 'distinct-id',
        elements_chain: 'a:href="https://example.com"',
        properties: { $current_url: 'https://example.com' },
        timestamp: '2026-01-01T00:00:00.000Z',
        url: 'https://example.com/events/1',
    },
    person: {
        id: '00000000-0000-0000-0000-000000000002',
        name: 'example',
        url: 'https://example.com/persons/1',
        properties: { email: 'person@example.com' },
    },
    groups: {
        organization: { id: 'org-1', type: 'organization', index: 0, url: '', properties: { plan: 'pro' } },
    },
    variables: { threshold: 10 },
}

const rawEvent: RawClickHouseEvent = {
    uuid: '00000000-0000-0000-0000-000000000001',
    event: '$pageview',
    team_id: 1,
    project_id: 1 as ProjectId,
    distinct_id: 'distinct-id',
    timestamp: '2026-01-01 00:00:00.000000' as ClickHouseTimestamp,
    created_at: '2026-01-01 00:00:00.000000' as ClickHouseTimestamp,
    properties: JSON.stringify({ $current_url: 'https://example.com' }),
    elements_chain: 'a:href="https://example.com"',
    person_id: '00000000-0000-0000-0000-000000000002',
    person_properties: JSON.stringify({ email: 'person@example.com' }),
    group0_properties: JSON.stringify({ plan: 'pro' }),
    person_mode: 'full',
    historical_migration: false,
}

// Below these the builders have almost certainly thrown inside and been swallowed; a near-empty
// file would otherwise pass the staleness check and reject every filter.
const MIN_ROOTS = 20
const MIN_CALLABLES = 100

/** Asks the runtime what it resolves, rather than transcribing a type or a table by hand. */
export function describeFilterRuntime(): FilterRuntime {
    const fromInvocation = Object.keys(convertToHogFunctionFilterGlobal(invocationGlobals)).sort()
    const fromRawEvent = Object.keys(convertClickhouseRawEventToFilterGlobals(rawEvent)).sort()
    if (JSON.stringify(fromInvocation) !== JSON.stringify(fromRawEvent)) {
        throw new Error(
            `The two filter-globals builders disagree.\n  invocation: ${fromInvocation.join(', ')}\n  raw event:  ${fromRawEvent.join(', ')}`
        )
    }

    // BYTECODE_STL is left out. GET_GLOBAL hands back a closure for one of its names, but CALL_LOCAL
    // resolves an 'stl' closure in STL only, so invoking that closure throws. Calling the same name
    // directly is unaffected: a call compiles to CALL_GLOBAL, which runs the BYTECODE_STL bytecode.
    // ASYNC_STL is a separate table today, so this removes nothing. It stays because GET_GLOBAL checks
    // ASYNC_STL first: a name added to both would be async at runtime, and the filter path allows no
    // async steps, so it must not be offered as a callable.
    // print writes to the process's stdout. The function body path replaces it with a logger; the
    // filter path runs the standard library as is, so a filter must not be able to reach it.
    const offered = (name: string): boolean => !Object.hasOwn(ASYNC_STL, name) && name !== 'print'
    const callables = Object.keys(STL).filter(offered).sort()
    const functions: Record<string, [number, number | null]> = {}
    for (const name of Object.keys(STL).filter(offered).sort()) {
        functions[name] = [STL[name].minArgs ?? 0, STL[name].maxArgs ?? null]
    }
    for (const name of Object.keys(BYTECODE_STL).filter(offered).sort()) {
        // The VM checks a bytecode function for exactly its declared parameters.
        functions[name] ??= [BYTECODE_STL[name][0].length, BYTECODE_STL[name][0].length]
    }

    if (fromInvocation.length < MIN_ROOTS || Object.keys(functions).length < MIN_CALLABLES) {
        throw new Error(
            `Suspiciously small runtime description: ${fromInvocation.length} roots, ${callables.length} callables`
        )
    }
    return { roots: fromInvocation, callables, functions, template_roots: Object.keys(templateRoots).sort() }
}

export function renderFilterGlobalsFile(runtime: FilterRuntime): string {
    return (
        JSON.stringify(
            {
                $comment:
                    'Generated. Do not edit: run `pnpm --filter=@posthog/nodejs run build:filter-globals`. ' +
                    'roots are the data globals the CDP filter runtime builds for a hog function. callables are ' +
                    'the standard-library names the VM hands back as values and can then invoke, so they are the ' +
                    'ones a filter can pass as a callback. functions are every standard-library name a filter can ' +
                    'call directly, with the argument count the VM enforces as [min, max]. template_roots are the ' +
                    'names an input template can read. Django reads this to refuse a filter or an input the ' +
                    'runtime could not evaluate.',
                roots: runtime.roots,
                callables: runtime.callables,
                functions: runtime.functions,
                template_roots: runtime.template_roots,
            },
            null,
            // Matches what the pre-commit hook (bin/hogli format:yaml) writes, so a regenerate is a no-op.
            4
        ) + '\n'
    )
}
