import { JSONContent } from 'lib/components/RichContentEditor/types'

import { collectNotebookFrameNodes, extractPythonIdentifiers } from '../Nodes/notebookNodeContent'
import { NotebookNodeType } from '../types'

export type NotebookVariableType = 'string' | 'number' | 'boolean' | 'date'

export const NOTEBOOK_VARIABLE_TYPES: NotebookVariableType[] = ['string', 'number', 'boolean', 'date']

/** Mirrors MAX_VARIABLES_PER_NOTEBOOK / MAX_VARIABLE_VALUE_CHARS in sql_v2_serializers.py,
 * so the bar stops at the limit instead of letting a save fail. */
export const MAX_NOTEBOOK_VARIABLES = 10
export const MAX_NOTEBOOK_VARIABLE_VALUE_CHARS = 1000

export type NotebookVariableValue = string | number | boolean | null

export type NotebookVariable = {
    name: string
    type: NotebookVariableType
    value: NotebookVariableValue
}

/**
 * HogQL injects its own `{filters}` placeholder into notebook queries, so a variable of that
 * name could never be read — the filter injection wins. Rejected at declaration rather than
 * silently shadowed.
 */
export const RESERVED_NOTEBOOK_VARIABLE_NAMES = new Set(['filters'])

/**
 * A variable is referenced as a bare `{name}` placeholder in SQL and as a plain global in
 * Python, so only a plain identifier can ever be resolved. Same rule as a cell's dataframe name.
 */
const VALID_VARIABLE_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/

const stripSqlComments = (sql: string): string => sql.replace(/--.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '')

/** String literals, blanked before scanning so a `'{country}'` inside a literal is not a reference. */
const SQL_STRING_LITERAL = /'(?:[^'\\]|\\.|'')*'/g

/**
 * The bare `{name}` placeholders a SQL cell reads. Comments and string literals are blanked
 * first, so only a real placeholder position counts.
 *
 * Deliberately the same single-brace form the legacy HogQLSQL cell uses for kernel globals:
 * that cell type is no longer insertable, and one syntax beats two in the cells people write now.
 */
export function extractSqlVariableReferences(sql: string): string[] {
    const scannable = stripSqlComments(sql || '').replace(SQL_STRING_LITERAL, ' ')
    const names: string[] = []
    const pattern = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g
    let match = pattern.exec(scannable)
    while (match) {
        if (!names.includes(match[1])) {
            names.push(match[1])
        }
        match = pattern.exec(scannable)
    }
    return names
}

function toVariableType(value: unknown): NotebookVariableType {
    return typeof value === 'string' && (NOTEBOOK_VARIABLE_TYPES as string[]).includes(value)
        ? (value as NotebookVariableType)
        : 'string'
}

function toVariableValue(value: unknown): NotebookVariableValue {
    if (value === undefined || value === null) {
        return null
    }
    return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? value : null
}

/**
 * Read the declarations off a notebook. Tolerant on purpose: the column is plain JSON that
 * older clients and the API can write, and one malformed entry must not blank the rest.
 */
export function parseNotebookVariables(value: unknown): NotebookVariable[] {
    if (!Array.isArray(value)) {
        return []
    }
    return value.flatMap((item): NotebookVariable[] => {
        if (!item || typeof item !== 'object' || Array.isArray(item)) {
            return []
        }
        const entry = item as Record<string, unknown>
        const type = toVariableType(entry.type)
        return [
            {
                name: typeof entry.name === 'string' ? entry.name.trim() : '',
                type,
                value: coerceNotebookVariableValue(type, toVariableValue(entry.value)),
            },
        ]
    })
}

/** Fit a value to its declared type, so a type switch in the editor never leaves a stale shape behind. */
export function coerceNotebookVariableValue(
    type: NotebookVariableType,
    value: NotebookVariableValue
): NotebookVariableValue {
    if (value === null) {
        return null
    }
    if (type === 'number') {
        const numeric = typeof value === 'number' ? value : Number(String(value).trim())
        return Number.isFinite(numeric) ? numeric : null
    }
    if (type === 'boolean') {
        return typeof value === 'boolean' ? value : String(value).trim().toLowerCase() === 'true'
    }
    return typeof value === 'string' ? value : String(value)
}

/** Names a variable must not take: every cell's output dataframe, which shares the kernel namespace. */
export function getNotebookVariableConflictNames(content?: JSONContent | null): Set<string> {
    return new Set(collectNotebookFrameNodes(content).map((node) => node.name))
}

/**
 * Per-declaration validation error, keyed by the variable's index, or null when the declaration
 * is usable. Uniqueness is checked against the other declarations and against cell dataframe
 * names: a Python cell reads both out of one kernel namespace, so a shared name means one
 * silently clobbers the other.
 */
export function getNotebookVariableErrors(
    variables: NotebookVariable[],
    conflictNames: Set<string> = new Set()
): (string | null)[] {
    const countsByName = variables.reduce<Record<string, number>>((counts, variable) => {
        counts[variable.name] = (counts[variable.name] ?? 0) + 1
        return counts
    }, {})

    return variables.map((variable, index) => {
        if (!variable.name) {
            return 'Give the variable a name.'
        }
        if (!VALID_VARIABLE_NAME.test(variable.name)) {
            const suggestion = variable.name.replace(/[^A-Za-z0-9_]/g, '_').replace(/^(?=\d)/, '_')
            const hint = VALID_VARIABLE_NAME.test(suggestion) ? ` Try ${suggestion}.` : ''
            // Name only the rule that was actually broken, so `look-back` isn't told it starts
            // with a number.
            const startsWithDigit = /^\d/.test(variable.name)
            const hasInvalidChars = /[^A-Za-z0-9_]/.test(variable.name)
            const reason =
                startsWithDigit && hasInvalidChars
                    ? "Use letters, numbers, and underscores, and don't start with a number."
                    : startsWithDigit
                      ? "The name can't start with a number."
                      : 'Use letters, numbers, and underscores.'
            return `${reason}${hint}`
        }
        if (RESERVED_NOTEBOOK_VARIABLE_NAMES.has(variable.name)) {
            return `${variable.name} is reserved by PostHog. Pick another name.`
        }
        if (countsByName[variable.name] > 1 && variables.findIndex((other) => other.name === variable.name) !== index) {
            return `${variable.name} is already declared. Names must be unique.`
        }
        if (conflictNames.has(variable.name)) {
            return `${variable.name} is already a cell's output dataframe. Names must be unique.`
        }
        return null
    })
}

/** Declarations that are safe to send to a run: named, valid, and unique. */
export function getRunnableNotebookVariables(
    variables: NotebookVariable[],
    conflictNames: Set<string> = new Set()
): NotebookVariable[] {
    const errors = getNotebookVariableErrors(variables, conflictNames)
    return variables.filter((_, index) => errors[index] === null)
}

/**
 * A row the person added but has not named yet. It cannot be referenced or saved, so the bar
 * treats it as a draft: no validation message, and no attempt to persist it.
 */
export function isNotebookVariableDraft(variable: NotebookVariable): boolean {
    return !variable.name
}

/**
 * The declarations the API accepts. Conflicts with a cell's dataframe name are deliberately not
 * filtered here: the server stores such a declaration happily, and dropping it would delete the
 * person's work because another cell was renamed. One bad row must not fail the whole PATCH.
 */
export function getSavableNotebookVariables(variables: NotebookVariable[]): NotebookVariable[] {
    const errors = getNotebookVariableErrors(variables)
    return variables.filter((_, index) => errors[index] === null)
}

/**
 * The saved declarations that `savable` would remove. A PATCH replaces the whole list, so this is
 * what the server would lose by sending it.
 */
export function droppedSavedNotebookVariables(
    savable: NotebookVariable[],
    saved: NotebookVariable[]
): NotebookVariable[] {
    const savableNames = new Set(savable.map((variable) => variable.name))
    return saved.filter((variable) => !savableNames.has(variable.name))
}

/** Whether two declaration lists hold the same variables in the same order. */
export function sameNotebookVariables(a: NotebookVariable[], b: NotebookVariable[]): boolean {
    return (
        a.length === b.length &&
        a.every(
            (variable, index) =>
                variable.name === b[index].name && variable.type === b[index].type && variable.value === b[index].value
        )
    )
}

/**
 * Whether a cell's code reads `variableName`. SQL reads it as a `{name}` placeholder; Python reads
 * it as a plain global, so the rough identifier scan is reused (a false positive only marks an
 * extra cell stale).
 */
export function cellReadsNotebookVariable(code: string, nodeType: NotebookNodeType, variableName: string): boolean {
    if (!variableName) {
        return false
    }
    return nodeType === NotebookNodeType.PythonV2
        ? extractPythonIdentifiers(code).includes(variableName)
        : extractSqlVariableReferences(code).includes(variableName)
}
