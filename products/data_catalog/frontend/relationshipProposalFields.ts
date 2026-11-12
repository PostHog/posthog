import type { relationshipsLogicValues } from './relationshipsLogic'

export const RELATIONSHIP_PROPOSAL_FIELDS = [
    ['source_table_name', 'Source table'],
    ['source_table_key', 'Source key'],
    ['joining_table_name', 'Related table'],
    ['joining_table_key', 'Related key'],
    ['field_name', 'Relationship name'],
] as const

export const RELATIONSHIP_PROPOSAL_REASONING_LABEL = 'Why should these tables be related?'

export function proposalDisabledReason(draft: relationshipsLogicValues['proposalDraft']): string | undefined {
    return RELATIONSHIP_PROPOSAL_FIELDS.some(([key]) => !draft[key].trim())
        ? 'Fill in both tables, keys, and a relationship name'
        : undefined
}
