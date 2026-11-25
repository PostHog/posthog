import type { ScopeFields } from './advancedActivityLogsLogic'

export const MAX_VISIBLE_DETAIL_FIELDS = 100

export interface DetailFieldChoice {
    fieldName: string
    leafName: string
    scopes: string[]
}

export interface VisibleDetailFieldChoice extends DetailFieldChoice {
    value: string
    isSelected: boolean
}

export interface DetailFieldSearch {
    searchTerm: string
    excludedFieldPaths: string[]
    selectedFieldPath?: string
    limit?: number
}

export interface VisibleDetailFieldChoices {
    visible: VisibleDetailFieldChoice[]
    selected: VisibleDetailFieldChoice | null
    matchCount: number
}

const fieldNameCollator = new Intl.Collator('en')

function splitFieldPath(fieldPath: string): [scope: string, fieldName: string] {
    const separatorIndex = fieldPath.indexOf('::')
    return separatorIndex === -1
        ? ['', fieldPath]
        : [fieldPath.slice(0, separatorIndex), fieldPath.slice(separatorIndex + 2)]
}

export function getDetailFieldChoices(detailFields: Record<string, ScopeFields> | undefined): DetailFieldChoice[] {
    if (!detailFields) {
        return []
    }

    const choicesByName = new Map<string, DetailFieldChoice & { depth: number }>()
    for (const [scope, scopeData] of Object.entries(detailFields)) {
        for (const field of scopeData.fields) {
            const choice = choicesByName.get(field.name)
            if (!choice) {
                const segments = field.name.split('.')
                choicesByName.set(field.name, {
                    fieldName: field.name,
                    leafName: segments[segments.length - 1] || field.name,
                    scopes: [scope],
                    depth: segments.length,
                })
            } else if (!choice.scopes.includes(scope)) {
                choice.scopes.push(scope)
            }
        }
    }

    return Array.from(choicesByName.values())
        .sort((a, b) => a.depth - b.depth || fieldNameCollator.compare(a.fieldName, b.fieldName))
        .map(({ depth: _depth, ...choice }) => choice)
}

function matchRank(choice: DetailFieldChoice, words: string[]): number | null {
    const leafName = choice.leafName.toLowerCase()
    if (words.every((word) => leafName.includes(word))) {
        if (leafName === words.join(' ')) {
            return 0
        }
        return leafName.startsWith(words[0]) ? 1 : 2
    }
    const searchText = `${choice.scopes.join(' ')} ${choice.fieldName}`.toLowerCase()
    return words.every((word) => searchText.includes(word)) ? 3 : null
}

type ToVisible = (choice: DetailFieldChoice) => VisibleDetailFieldChoice | null

function makeToVisible(excludedFieldPaths: string[], selectedFieldPath: string | undefined): ToVisible {
    const excludedFieldNames = new Set(excludedFieldPaths.map((fieldPath) => splitFieldPath(fieldPath)[1]))
    const [selectedScope, selectedFieldName] = selectedFieldPath ? splitFieldPath(selectedFieldPath) : [null, null]

    return (choice) => {
        if (choice.fieldName === selectedFieldName && selectedScope && choice.scopes.includes(selectedScope)) {
            return { ...choice, value: `${selectedScope}::${choice.fieldName}`, isSelected: true }
        }
        return excludedFieldNames.has(choice.fieldName)
            ? null
            : { ...choice, value: `${choice.scopes[0]}::${choice.fieldName}`, isSelected: false }
    }
}

function findSelected(choices: DetailFieldChoice[], toVisible: ToVisible): VisibleDetailFieldChoice | null {
    for (const choice of choices) {
        const candidate = toVisible(choice)
        if (candidate?.isSelected) {
            return candidate
        }
    }
    return null
}

function listAll(
    choices: DetailFieldChoice[],
    toVisible: ToVisible,
    limit: number
): Pick<VisibleDetailFieldChoices, 'visible' | 'matchCount'> {
    const visible: VisibleDetailFieldChoice[] = []
    let matchCount = 0
    for (const choice of choices) {
        const candidate = toVisible(choice)
        if (!candidate) {
            continue
        }
        matchCount += 1
        if (candidate.isSelected) {
            visible.unshift(candidate)
        } else if (visible.length < limit) {
            visible.push(candidate)
        }
    }
    return { visible: visible.slice(0, limit), matchCount }
}

function listMatches(
    choices: DetailFieldChoice[],
    toVisible: ToVisible,
    words: string[],
    limit: number
): Pick<VisibleDetailFieldChoices, 'visible' | 'matchCount'> {
    const ranked: VisibleDetailFieldChoice[][] = [[], [], [], []]
    let matchCount = 0
    for (const choice of choices) {
        const rank = matchRank(choice, words)
        const candidate = rank === null ? null : toVisible(choice)
        if (candidate && rank !== null) {
            matchCount += 1
            if (ranked[rank].length < limit) {
                ranked[rank].push(candidate)
            }
        }
    }
    return { visible: ranked.flat().slice(0, limit), matchCount }
}

export function getVisibleDetailFieldChoices(
    choices: DetailFieldChoice[],
    { searchTerm, excludedFieldPaths, selectedFieldPath, limit = MAX_VISIBLE_DETAIL_FIELDS }: DetailFieldSearch
): VisibleDetailFieldChoices {
    const toVisible = makeToVisible(excludedFieldPaths, selectedFieldPath)
    const words = searchTerm.toLowerCase().split(/\s+/).filter(Boolean)
    const list = words.length === 0 ? listAll(choices, toVisible, limit) : listMatches(choices, toVisible, words, limit)

    return { ...list, selected: selectedFieldPath ? findSelected(choices, toVisible) : null }
}
