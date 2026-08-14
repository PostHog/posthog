import { parseMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'
import { NotebookComponentProps, NotebookPropValue } from 'lib/components/MarkdownNotebook/types'
import { JSONContent } from 'lib/components/RichContentEditor/types'

import { collectNotebookFrameNodes, extractPythonIdentifiers } from '../Nodes/notebookNodeContent'
import { NotebookNodeType } from '../types'

/** The markdown tag holding a notebook's variable declarations. Stable — renaming it is a content migration. */
export const NOTEBOOK_VARIABLES_TAG = 'Variables'

export type NotebookVariableType = 'string' | 'number' | 'boolean' | 'date'

export const NOTEBOOK_VARIABLE_TYPES: NotebookVariableType[] = ['string', 'number', 'boolean', 'date']

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

function toVariableType(value: NotebookPropValue | undefined): NotebookVariableType {
    return typeof value === 'string' && (NOTEBOOK_VARIABLE_TYPES as string[]).includes(value)
        ? (value as NotebookVariableType)
        : 'string'
}

function toVariableValue(value: NotebookPropValue | undefined): NotebookVariableValue {
    if (value === undefined || value === null) {
        return null
    }
    return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? value : null
}

/**
 * Read the declarations out of a `<Variables>` block's props. Tolerant on purpose: the props are
 * hand-editable markdown, and one malformed entry must not blank the whole block.
 */
export function parseNotebookVariableItems(props: NotebookComponentProps): NotebookVariable[] {
    const items = props.items
    if (!Array.isArray(items)) {
        return []
    }
    return items.flatMap((item): NotebookVariable[] => {
        if (!item || typeof item !== 'object' || Array.isArray(item)) {
            return []
        }
        const name = typeof item.name === 'string' ? item.name.trim() : ''
        const type = toVariableType(item.type)
        return [{ name, type, value: coerceNotebookVariableValue(type, toVariableValue(item.value)) }]
    })
}

export function serializeNotebookVariableItems(variables: NotebookVariable[]): NotebookPropValue {
    return variables.map((variable) => ({ name: variable.name, type: variable.type, value: variable.value }))
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

/**
 * Every variable declared in the notebook, in document order. Duplicate names keep the first
 * declaration — the later one is reported as an error by `getNotebookVariableErrors` rather than
 * silently shadowing, so what runs is always the one the editor flags as valid.
 */
export function collectNotebookVariables(content?: JSONContent | null): NotebookVariable[] {
    const variables: NotebookVariable[] = []
    const seen = new Set<string>()

    for (const declared of collectDeclaredNotebookVariables(content)) {
        if (!declared.name || seen.has(declared.name)) {
            continue
        }
        seen.add(declared.name)
        variables.push(declared)
    }

    return variables
}

/** Every declaration as written, duplicates included — what the editor validates against. */
export function collectDeclaredNotebookVariables(content?: JSONContent | null): NotebookVariable[] {
    if (!content || typeof content !== 'object') {
        return []
    }

    const declared: NotebookVariable[] = []

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === NotebookNodeType.MarkdownNotebook && typeof node.attrs?.markdown === 'string') {
            for (const block of parseMarkdownNotebook(node.attrs.markdown).nodes) {
                if (block.type === 'component' && block.tagName === NOTEBOOK_VARIABLES_TAG) {
                    declared.push(...parseNotebookVariableItems(block.props))
                }
            }
        }
        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)
    return declared
}

/** Names a variable must not take: every cell's output dataframe, which shares the kernel namespace. */
export function getNotebookVariableConflictNames(content?: JSONContent | null): Set<string> {
    return new Set(collectNotebookFrameNodes(content).map((node) => node.name))
}

/**
 * Per-declaration validation error, keyed by the variable's index in the block, or null when the
 * declaration is usable. Uniqueness is checked against the other declarations and against cell
 * dataframe names: a Python cell reads both out of one kernel namespace, so a shared name means
 * one silently clobbers the other.
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
