import {
    ArrayExpr,
    CoalesceExpr,
    Expr,
    InterpExpr,
    JoinExpr,
    LiteralExpr,
    ObjectExpr,
    OmitExpr,
    PathExpr,
    RejectExpr,
    SelectExpr,
    SelfExpr,
    StringifyExpr,
    TryParseStructuredContentExpr,
} from '../ast/expr'
import {
    EqualsPredicate,
    ExistsPredicate,
    EveryPredicate,
    InPredicate,
    IsPredicate,
    Pattern,
    Predicate,
    ShapePredicate,
    TypeName,
} from '../ast/predicate'
import { DelegateEachRule, DelegateRule, EmitRule, Rule } from '../ast/rule'
import { EmitSpec, FollowupSpec, RoleTag } from '../spec/emitSpec'
import { Recipe } from '../spec/recipe'
import { nearestOperator } from './operatorSuggestion'

const PREDICATE_VERBS = new Set(['equals', 'exists', 'is', 'in', 'shape', 'every'])
const ROLE_TAGS: ReadonlySet<RoleTag> = new Set(['user', 'assistant', 'system', 'tool', 'thinking', 'tool_result'])
const TYPE_NAMES: ReadonlySet<TypeName> = new Set(['string', 'array', 'object', 'null', 'number', 'boolean', 'any'])
const OPERATORS = new Set([
    'select',
    'reject',
    'coalesce',
    'join',
    'omit',
    'try_parse_structured_content',
    'stringify',
    'literal',
])

const BARE_FIELD_RE = /^[A-Za-z_]\w*$/

// `fallbackId` is the identity to use when the yaml omits `id:` — custom recipes are
// keyed by their database id, so their source never needs to declare one. Bundled
// recipes pass no fallback and must declare their id.
export function compileRecipe(raw: unknown, fallbackId?: string): Recipe {
    if (!isObject(raw)) {
        throw new Error(`Recipe YAML must be a mapping at top level`)
    }
    const id = stringField(raw, 'id') ?? fallbackId
    if (!id) {
        throw new Error(`Recipe is missing an 'id' key`)
    }
    const rulesRaw = raw.rules
    if (!Array.isArray(rulesRaw)) {
        throw new Error(`Recipe '${id}' is missing a 'rules:' sequence`)
    }
    return {
        id,
        rules: rulesRaw.map((r, i) => {
            try {
                return compileRule(r)
            } catch (err) {
                throw new Error(`Recipe '${id}' rule[${i}]: ${err instanceof Error ? err.message : String(err)}`)
            }
        }),
    }
}

function compileRule(raw: unknown): Rule {
    if (!isObject(raw)) {
        throw new Error(`rule must be a mapping`)
    }
    if (!isObject(raw.on)) {
        throw new Error(`rule.on must be a mapping`)
    }
    const on = compilePattern(raw.on)
    const followups = compileFollowups(raw.followups)

    if (raw.delegate !== undefined) {
        return new DelegateRule(on, followups, compileValue(raw.delegate))
    }
    if (raw.delegateEach !== undefined) {
        const stamp = raw.stamp !== undefined ? compileEmitSpec(raw.stamp) : null
        return new DelegateEachRule(on, followups, compileValue(raw.delegateEach), stamp)
    }
    if (raw.emit !== undefined) {
        return new EmitRule(on, followups, compileEmitSpec(raw.emit))
    }
    throw new Error('Rule must set one of: emit, delegate, delegateEach')
}

function compileFollowups(raw: unknown): FollowupSpec[] {
    if (raw === undefined) {
        return []
    }
    if (!Array.isArray(raw)) {
        throw new Error(`rule.followups must be a sequence`)
    }
    return raw.map(compileFollowup)
}

function compileFollowup(raw: unknown): FollowupSpec {
    if (!isObject(raw)) {
        throw new Error(`followup entry must be a mapping`)
    }
    if ('from' in raw && 'each' in raw) {
        if (!isObject(raw.each)) {
            throw new Error(`'each:' in followup must be a mapping`)
        }
        return { kind: 'expand', from: compileValue(raw.from), each: compileEmitSpec(raw.each) }
    }
    return { kind: 'static', emit: compileEmitSpec(raw) }
}

function compilePattern(raw: Record<string, unknown>): Pattern {
    const fields: Record<string, Predicate> = {}
    for (const [key, value] of Object.entries(raw)) {
        fields[key] = compilePredicate(value)
    }
    return new Pattern(fields)
}

function compilePredicate(raw: unknown): Predicate {
    if (isObject(raw)) {
        const keys = Object.keys(raw)
        const verbs = keys.filter((k) => PREDICATE_VERBS.has(k))
        if (verbs.length > 1) {
            throw new Error(`predicate has multiple verbs (${verbs.join(', ')}); use one verb per field`)
        }
        if (verbs.length === 1) {
            if (keys.length > 1) {
                const fields = keys.filter((k) => !PREDICATE_VERBS.has(k))
                throw new Error(`predicate verb '${verbs[0]}' cannot be mixed with field keys (${fields.join(', ')})`)
            }
            return buildPredicateFromVerb(verbs[0], raw[verbs[0]])
        }
        return new ShapePredicate(compilePattern(raw))
    }
    return new EqualsPredicate(raw)
}

function buildPredicateFromVerb(verb: string, value: unknown): Predicate {
    switch (verb) {
        case 'equals':
            return new EqualsPredicate(value)
        case 'exists':
            return new ExistsPredicate(Boolean(value))
        case 'is': {
            const arr = Array.isArray(value) ? value : [value]
            const types: TypeName[] = []
            for (const t of arr) {
                // YAML bare `null` parses as JS null, but inside `is: [...]` the
                // author meant the type name 'null'. Normalize either to 'null'.
                const name = t === null ? 'null' : t
                if (typeof name !== 'string' || !TYPE_NAMES.has(name as TypeName)) {
                    throw new Error(`'is:' must be a type or array of types, got ${JSON.stringify(value)}`)
                }
                types.push(name as TypeName)
            }
            return new IsPredicate(types)
        }
        case 'in':
            if (!Array.isArray(value)) {
                throw new Error(`'in:' must be an array`)
            }
            return new InPredicate(value)
        case 'shape':
            if (!isObject(value)) {
                throw new Error(`'shape:' must be a mapping`)
            }
            return new ShapePredicate(compilePattern(value))
        case 'every':
            return new EveryPredicate(compilePredicate(value))
        default:
            throw new Error(`Unknown predicate verb '${verb}'`)
    }
}

function compileEmitSpec(raw: unknown): EmitSpec {
    if (!isObject(raw)) {
        throw new Error(`emit must be a mapping`)
    }
    const out: EmitSpec = {}
    for (const [k, v] of Object.entries(raw)) {
        switch (k) {
            case 'role':
                out.role = typeof v === 'string' && ROLE_TAGS.has(v as RoleTag) ? (v as RoleTag) : compileValue(v)
                break
            case 'content':
                out.content = compileValue(v)
                break
            case 'toolCall':
                out.toolCall = compileValue(v)
                break
            case 'toolCalls':
                out.toolCalls = compileValue(v)
                break
            case 'toolCallId':
            case 'tool_call_id':
                out.toolCallId = compileValue(v)
                break
            case 'spread':
                out.spread = compileValue(v)
                break
            default:
                throw new Error(`Unknown emit key '${k}'`)
        }
    }
    return out
}

function compileValue(raw: unknown): Expr {
    if (raw === null || raw === undefined) {
        return new LiteralExpr(null)
    }
    if (typeof raw === 'number' || typeof raw === 'boolean') {
        return new LiteralExpr(raw)
    }
    if (typeof raw === 'string') {
        return compileStringValue(raw)
    }
    if (Array.isArray(raw)) {
        return new ArrayExpr(raw.map(compileValue))
    }
    if (isObject(raw)) {
        const keys = Object.keys(raw)
        if (keys.length === 1) {
            const key = keys[0]
            if (OPERATORS.has(key)) {
                return compileOperator(key, raw[key])
            }
            const suggestion = nearestOperator(key, OPERATORS)
            if (suggestion) {
                throw new Error(
                    `Unknown operator '${key}'. Did you mean '${suggestion}'? ` +
                        `Wrap an intentional one-key object in 'literal:'.`
                )
            }
        }
        const fields: Record<string, Expr> = {}
        for (const [k, v] of Object.entries(raw)) {
            fields[k] = compileValue(v)
        }
        return new ObjectExpr(fields)
    }
    return new LiteralExpr(raw)
}

// Requires an identifier after `$.` so a stray `$` in a URL or price isn't read as a path.
const INTERP_RE = /\$\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)/g

function compileStringValue(s: string): Expr {
    if (s === '$') {
        return new SelfExpr()
    }
    if (/^\$\.[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$/.test(s)) {
        return new PathExpr(s.slice(2).split('.').filter(Boolean))
    }
    if (s.startsWith('$') && /^[$][A-Za-z_]/.test(s)) {
        throw new Error(
            `'${s}' is not a valid value expression. Use '$.${s.slice(1)}' for a field read, or '$' for the whole input.`
        )
    }
    INTERP_RE.lastIndex = 0
    if (INTERP_RE.test(s)) {
        return compileInterp(s)
    }
    return new LiteralExpr(s)
}

function compileInterp(s: string): Expr {
    const parts: (string | Expr)[] = []
    INTERP_RE.lastIndex = 0
    let cursor = 0
    let m: RegExpExecArray | null
    while ((m = INTERP_RE.exec(s)) !== null) {
        if (m.index > cursor) {
            parts.push(s.slice(cursor, m.index))
        }
        parts.push(new PathExpr(m[1].split('.')))
        cursor = m.index + m[0].length
    }
    if (cursor < s.length) {
        parts.push(s.slice(cursor))
    }
    return new InterpExpr(parts)
}

function compileOperator(op: string, payload: unknown): Expr {
    switch (op) {
        // Escape hatch for an intentional one-key data object whose key collides
        // with an operator name; the payload is kept uncompiled.
        case 'literal':
            return new LiteralExpr(payload)
        case 'coalesce':
            return new CoalesceExpr(compileCoalesceFrom(payload))
        case 'try_parse_structured_content':
            return new TryParseStructuredContentExpr(compileValue(payload))
        case 'stringify':
            return new StringifyExpr(compileValue(payload))
        case 'join': {
            const args = asOperatorMapping(op, payload)
            return new JoinExpr(operatorArg(args, 'from'), optionalArg(args, 'sep'), optionalArg(args, 'field'))
        }
        case 'omit': {
            const args = asOperatorMapping(op, payload)
            return new OmitExpr(operatorArg(args, 'from'), optionalArg(args, 'keys'))
        }
        case 'select': {
            const args = asOperatorMapping(op, payload)
            return new SelectExpr(
                operatorArg(args, 'from'),
                compileWhere(args.where),
                compilePluck(args.pluck),
                optionalArg(args, 'if_empty')
            )
        }
        case 'reject': {
            const args = asOperatorMapping(op, payload)
            return new RejectExpr(operatorArg(args, 'from'), compileWhere(args.where), optionalArg(args, 'if_empty'))
        }
        default:
            throw new Error(`Unknown operator: ${op}`)
    }
}

function compileCoalesceFrom(payload: unknown): Expr {
    if (Array.isArray(payload)) {
        return new ArrayExpr(payload.map(compileValue))
    }
    if (!isObject(payload)) {
        throw new Error(`'coalesce:' takes an array or {from: [...]}`)
    }
    return operatorArg(payload, 'from')
}

function compileWhere(raw: unknown): Pattern | null {
    if (raw === undefined) {
        return null
    }
    if (!isObject(raw)) {
        throw new Error(`'where:' must be a mapping`)
    }
    return compilePattern(raw)
}

function compilePluck(raw: unknown): Expr | null {
    if (raw === undefined) {
        return null
    }
    if (typeof raw === 'string' && BARE_FIELD_RE.test(raw)) {
        return new PathExpr([raw])
    }
    return compileValue(raw)
}

function asOperatorMapping(op: string, payload: unknown): Record<string, unknown> {
    if (!isObject(payload)) {
        throw new Error(`'${op}:' takes a mapping`)
    }
    return payload
}

function operatorArg(args: Record<string, unknown>, key: string): Expr {
    if (!(key in args)) {
        throw new Error(`operator requires a '${key}:' argument`)
    }
    return compileValue(args[key])
}

function optionalArg(args: Record<string, unknown>, key: string): Expr | null {
    return key in args ? compileValue(args[key]) : null
}

function isObject(v: unknown): v is Record<string, unknown> {
    return !!v && typeof v === 'object' && !Array.isArray(v)
}

function stringField(o: Record<string, unknown>, key: string): string | undefined {
    const value = o[key]
    return typeof value === 'string' ? value : undefined
}
