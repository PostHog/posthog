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

export function getVisibleDetailFieldChoices(
    choices: DetailFieldChoice[],
    { searchTerm, excludedFieldPaths, selectedFieldPath, limit = MAX_VISIBLE_DETAIL_FIELDS }: DetailFieldSearch
): VisibleDetailFieldChoices {
    const excludedFieldNames = new Set(excludedFieldPaths.map((fieldPath) => splitFieldPath(fieldPath)[1]))
    const [selectedScope, selectedFieldName] = selectedFieldPath ? splitFieldPath(selectedFieldPath) : [null, null]

    const toVisible = (choice: DetailFieldChoice): VisibleDetailFieldChoice | null => {
        if (choice.fieldName === selectedFieldName && selectedScope && choice.scopes.includes(selectedScope)) {
            return { ...choice, value: `${selectedScope}::${choice.fieldName}`, isSelected: true }
        }
        return excludedFieldNames.has(choice.fieldName)
            ? null
            : { ...choice, value: `${choice.scopes[0]}::${choice.fieldName}`, isSelected: false }
    }

    const words = searchTerm.toLowerCase().split(/\s+/).filter(Boolean)
    let selected: VisibleDetailFieldChoice | null = null
    let matchCount = 0

    if (words.length === 0) {
        const others: VisibleDetailFieldChoice[] = []
        for (const choice of choices) {
            const candidate = toVisible(choice)
            if (!candidate) {
                continue
            }
            matchCount += 1
            if (candidate.isSelected) {
                selected = candidate
            } else if (others.length < limit) {
                others.push(candidate)
            }
        }
        const visible = selected ? [selected, ...others.slice(0, limit - 1)] : others
        return { visible, selected, matchCount }
    }

    const ranked: VisibleDetailFieldChoice[][] = [[], [], [], []]
    for (const choice of choices) {
        const rank = matchRank(choice, words)
        const candidate = rank !== null || choice.fieldName === selectedFieldName ? toVisible(choice) : null
        if (candidate?.isSelected) {
            selected = candidate
        }
        if (candidate && rank !== null) {
            matchCount += 1
            if (ranked[rank].length < limit) {
                ranked[rank].push(candidate)
            }
        }
    }
    return { visible: ranked.flat().slice(0, limit), selected, matchCount }
}
