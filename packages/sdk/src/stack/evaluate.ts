import { existsSync } from 'node:fs'
import { isAbsolute, relative, resolve, sep } from 'node:path'

import { type Definition, dependenciesOf, isDefinition, issuesOf, REF_TARGET } from '../define/definition.js'
import type { JsonObject, JsonValue } from '../types.js'
import {
    compareResources,
    DESCRIPTION_VERSION,
    formatPath,
    isRefValue,
    type RefValue,
    type ResourceDependency,
    type ResourceDescription,
    type StackDescription,
    type StackProblem,
    sortKeys,
} from './description.js'

export interface EvaluateOptions {
    // The repository root. Source files are recorded relative to it.
    root: string
    // The stack folder. A definition from a file outside it is reported, not collected. Without it,
    // every definition the exports reach is collected.
    stackDir?: string
}

export interface ResourceOrigin {
    file?: string
    export?: string
    dashboard?: string
    tile?: string
}

export interface Evaluation {
    description: StackDescription
    problems: StackProblem[]
    // By `kind:key`, where each resource was declared, for messages.
    origins: Map<string, ResourceOrigin>
    // `kind:key` of definitions the stack reached but did not collect, because they live outside
    // its folder. Validation does not report refs to them again.
    excluded: Set<string>
}

interface Where {
    kind: string
    key: string
    file?: string
}

interface Found {
    definition: Definition
    body: JsonObject
    origin: ResourceOrigin
}

export function resourceId(kind: string, key: string): string {
    return `${kind}:${key}`
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const prototype = Object.getPrototypeOf(value)
    return prototype === Object.prototype || prototype === null
}

function describeValue(value: unknown): string {
    if (typeof value === 'function') {
        return 'a function'
    }
    if (typeof value === 'bigint') {
        return 'a bigint'
    }
    if (typeof value === 'symbol') {
        return 'a symbol'
    }
    if (typeof value === 'number') {
        return String(value)
    }
    const name = (value as object | null)?.constructor?.name
    return name ? `a ${name}` : 'an object'
}

function inside(folder: string, file: string): boolean {
    const path = relative(folder, file)
    return path !== '' && !path.startsWith('..') && !isAbsolute(path)
}

// Walks every export of the stack's index, and every definition those reference, into the
// description. Nothing here reads the clock, the network or the environment.
export function evaluateExports(exports: Record<string, unknown>, options: EvaluateOptions): Evaluation {
    const root = resolve(options.root)
    const stackDir = options.stackDir === undefined ? undefined : resolve(options.stackDir)
    const problems: StackProblem[] = []
    const found = new Map<string, Found>()
    const visited = new Set<Definition>()
    const serializing = new Set<Definition>()
    const exportNames = new Map<Definition, string>()
    const excluded = new Set<string>()
    // By the `kind:key` of the resource whose body named them.
    const dependencies = new Map<string, Map<string, ResourceDependency>>()

    // The first frame inside the stack folder that names a file which exists. Anything else, such
    // as a bundle or a source map that points elsewhere, gives no source rather than a wrong one.
    const sourceFile = (definition: Definition): { file?: string; outside: boolean } => {
        const frames = definition.origin.frames ?? (definition.origin.file ? [definition.origin.file] : [])
        if (frames.length === 0) {
            return { outside: false }
        }
        const scope = stackDir ?? root
        const file = frames.find((frame) => isAbsolute(frame) && inside(scope, frame) && existsSync(frame))
        if (!file) {
            return {
                outside:
                    stackDir !== undefined && frames.every((frame) => isAbsolute(frame) && !inside(stackDir, frame)),
            }
        }
        const fromRoot = relative(root, file)
        return fromRoot.startsWith('..') || isAbsolute(fromRoot)
            ? { outside: false }
            : { file: fromRoot.split(sep).join('/'), outside: false }
    }

    const collect = (definition: Definition, from: Where | undefined): void => {
        if (visited.has(definition)) {
            return
        }
        visited.add(definition)
        const id = resourceId(definition.kind, definition.key)
        const { file, outside } = sourceFile(definition)
        if (outside) {
            excluded.add(id)
            problems.push({
                code: 'outside_stack',
                severity: 'error',
                ...(from ?? { kind: definition.kind, key: definition.key }),
                message: `The ${definition.kind} ${definition.key} is defined outside this stack's folder. A stack holds only its own definitions: move it into the folder, or refer to it with ref('${definition.kind}', '${definition.key}') if this stack defines it elsewhere.`,
            })
            return
        }
        const exportName = exportNames.get(definition)
        const origin: ResourceOrigin = {
            ...(file ? { file } : {}),
            ...(exportName ? { export: exportName } : {}),
            ...(definition.origin.dashboard ? { dashboard: definition.origin.dashboard } : {}),
            ...(definition.origin.tile ? { tile: definition.origin.tile } : {}),
        }
        const existing = found.get(id)
        if (existing) {
            problems.push(duplicateProblem(definition, existing.origin, origin))
            return
        }
        // Reserved before the body is walked, so a definition inside it with the same identity is a duplicate.
        const entry: Found = { definition, body: {}, origin }
        found.set(id, entry)
        serializing.add(definition)
        const where: Where = { kind: definition.kind, key: definition.key, ...(file ? { file } : {}) }
        const body = toJson(definition.body, [], where, new Set())
        serializing.delete(definition)
        if (body !== null && typeof body === 'object' && !Array.isArray(body)) {
            entry.body = body
        } else {
            problems.push({
                code: 'body_invalid',
                severity: 'error',
                ...where,
                message: `The ${definition.kind} ${definition.key} must be an object of fields.`,
            })
        }
    }

    function toJson(
        value: unknown,
        path: (string | number)[],
        where: Where,
        ancestors: Set<object>
    ): JsonValue | undefined {
        if (value === undefined) {
            return undefined
        }
        if (value === null || typeof value === 'string' || typeof value === 'boolean') {
            return value
        }
        if (typeof value === 'number') {
            if (Number.isFinite(value)) {
                return value
            }
            problems.push(valueProblem(where, path, value))
            return null
        }
        if (isDefinition(value)) {
            if (serializing.has(value)) {
                problems.push({
                    code: 'reference_cycle',
                    severity: 'error',
                    ...where,
                    path: formatPath(path),
                    message: `The ${value.kind} ${value.key} refers back to itself through its own fields.`,
                })
            } else {
                collect(value, where)
            }
            return { $ref: { kind: value.kind, key: value.key } }
        }
        if (isRefValue(value)) {
            const target = (value as { [REF_TARGET]?: unknown })[REF_TARGET]
            if (isDefinition(target) && !serializing.has(target)) {
                collect(target, where)
            }
            const { kind, key, attr } = value.$ref
            const normalized: RefValue = { $ref: { kind, key, ...(attr && attr !== 'id' ? { attr } : {}) } }
            return normalized as unknown as JsonValue
        }
        if (typeof value === 'object' && ancestors.has(value)) {
            problems.push({
                code: 'value_invalid',
                severity: 'error',
                ...where,
                path: formatPath(path),
                message: `${formatPath(path) || 'The body'} contains itself. A definition holds plain JSON, which cannot loop.`,
            })
            return null
        }
        if (Array.isArray(value)) {
            const inner = new Set(ancestors).add(value)
            return value.map((item, index) => toJson(item, [...path, index], where, inner) ?? null)
        }
        if (isPlainObject(value)) {
            for (const dependency of dependenciesOf(value)) {
                const named = dependencies.get(resourceId(where.kind, where.key)) ?? new Map()
                named.set(resourceId(dependency.kind, dependency.key), { kind: dependency.kind, key: dependency.key })
                dependencies.set(resourceId(where.kind, where.key), named)
                // A definition from outside the folder is not collected: check reports the entry.
                if (!serializing.has(dependency) && !sourceFile(dependency).outside) {
                    collect(dependency, where)
                }
            }
            for (const issue of issuesOf(value)) {
                const at = formatPath([...path, ...(issue.path ? issue.path.split('.') : [])])
                problems.push({
                    code: issue.code,
                    severity: 'error',
                    ...where,
                    ...(at ? { path: at } : {}),
                    message: issue.message,
                })
            }
            const inner = new Set(ancestors).add(value)
            const object: JsonObject = {}
            for (const name of Object.keys(value).sort()) {
                const converted = toJson(value[name], [...path, name], where, inner)
                if (converted !== undefined) {
                    object[name] = converted
                }
            }
            return object
        }
        problems.push(valueProblem(where, path, value))
        return null
    }

    const names = Object.keys(exports).sort()
    // Export names first, so a definition that one export names and another references gets its name.
    for (const name of names) {
        walkExport(exports[name], new Set(), (definition) => {
            if (!exportNames.has(definition)) {
                exportNames.set(definition, name)
            }
        })
    }
    for (const name of names) {
        walkExport(exports[name], new Set(), (definition) => collect(definition, undefined))
    }

    addTileDashboards(found)

    const origins = new Map<string, ResourceOrigin>()
    const resources: ResourceDescription[] = [...found.values()]
        .map(({ definition, body, origin }) => {
            const id = resourceId(definition.kind, definition.key)
            origins.set(id, origin)
            const dependsOn = dependsOnOf(id, body, dependencies.get(id))
            return {
                kind: definition.kind,
                key: definition.key,
                body: sortKeys(body) as JsonObject,
                ...(origin.file
                    ? { source: { file: origin.file, ...(origin.export ? { export: origin.export } : {}) } }
                    : {}),
                ...(dependsOn.length > 0 ? { depends_on: dependsOn } : {}),
            }
        })
        .sort(compareResources)

    return { description: { version: DESCRIPTION_VERSION, resources }, problems, origins, excluded }
}

function refTargets(value: JsonValue, into: Set<string>): void {
    if (isRefValue(value)) {
        into.add(resourceId(value.$ref.kind, value.$ref.key))
    } else if (Array.isArray(value)) {
        value.forEach((item) => refTargets(item, into))
    } else if (value !== null && typeof value === 'object') {
        Object.values(value).forEach((item) => refTargets(item, into))
    }
}

// A `$ref` already orders its target first, so `depends_on` lists only the rest.
function dependsOnOf(
    id: string,
    body: JsonObject,
    named: Map<string, ResourceDependency> | undefined
): ResourceDependency[] {
    if (!named) {
        return []
    }
    const referenced = new Set<string>()
    refTargets(body, referenced)
    return [...named.entries()]
        .filter(([target]) => target !== id && !referenced.has(target))
        .map(([, dependency]) => dependency)
        .sort(compareResources)
}

function walkExport(value: unknown, seen: Set<unknown>, visit: (definition: Definition) => void): void {
    if (typeof value !== 'object' || value === null || seen.has(value)) {
        return
    }
    seen.add(value)
    if (isDefinition(value)) {
        visit(value)
        return
    }
    const items = Array.isArray(value) ? value : isPlainObject(value) ? Object.values(value) : []
    for (const item of items) {
        walkExport(item, seen, visit)
    }
}

// A tile shows an insight on its dashboard, so the insight's `dashboards` lists that dashboard, as
// the API's own insight body does. A `dashboards` the author wrote as something other than a list
// is left alone, so its schema check still fails.
function addTileDashboards(found: Map<string, Found>): void {
    for (const { definition, body } of found.values()) {
        if (definition.kind !== 'dashboard' || !Array.isArray(body.tiles)) {
            continue
        }
        for (const entry of body.tiles) {
            const insightRef = (entry as JsonObject | null)?.insight
            if (!isRefValue(insightRef) || insightRef.$ref.kind !== 'insight' || insightRef.$ref.attr) {
                continue
            }
            const target = found.get(resourceId('insight', insightRef.$ref.key))
            if (!target || (target.body.dashboards !== undefined && !Array.isArray(target.body.dashboards))) {
                continue
            }
            const listed = (target.body.dashboards as JsonValue[] | undefined) ?? []
            const already = listed.some(
                (item) => isRefValue(item) && item.$ref.kind === 'dashboard' && item.$ref.key === definition.key
            )
            if (!already) {
                const dashboardRef: RefValue = { $ref: { kind: 'dashboard', key: definition.key } }
                target.body.dashboards = [...listed, dashboardRef as unknown as JsonValue].sort((a, b) =>
                    JSON.stringify(a) < JSON.stringify(b) ? -1 : 1
                )
            }
        }
    }
}

function valueProblem(where: Where, path: (string | number)[], value: unknown): StackProblem {
    return {
        code: 'value_invalid',
        severity: 'error',
        ...where,
        path: formatPath(path),
        message: `${formatPath(path) || 'The body'} is ${describeValue(value)}. A definition holds plain JSON: strings, numbers, booleans, null, lists, objects and other definitions.`,
    }
}

function duplicateProblem(definition: Definition, first: ResourceOrigin, second: ResourceOrigin): StackProblem {
    const where = (origin: ResourceOrigin): string =>
        origin.dashboard !== undefined
            ? `a tile of dashboard ${origin.dashboard}${origin.file ? ` in ${origin.file}` : ''}`
            : (origin.file ?? 'a file check could not place')
    const fromTiles = first.dashboard !== undefined || second.dashboard !== undefined
    return {
        code: 'key_duplicate',
        severity: 'error',
        kind: definition.kind,
        key: definition.key,
        ...(second.file ? { file: second.file } : {}),
        message: `Two ${definition.kind} definitions use the key ${definition.key}: ${where(first)} and ${where(second)}. Each definition needs its own key.${fromTiles ? ' Give one of the tiles a key with tile(insight, { key }).' : ''}`,
    }
}
