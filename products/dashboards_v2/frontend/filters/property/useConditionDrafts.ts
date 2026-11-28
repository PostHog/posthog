import { useRef, useState } from 'react'

import type { PropertyOperator } from '~/types'

import { type PropertyCondition, isCompleteCondition } from './propertyOperators'

export type Draft = PropertyCondition & {
    id: number
}

function firstIncomplete(drafts: Draft[]): number | null {
    return drafts.find((draft) => !isCompleteCondition(draft))?.id ?? null
}

function completeOf(drafts: Draft[]): PropertyCondition[] {
    return drafts.filter(isCompleteCondition).map(({ operator, value }) => ({ operator, value }))
}

/**
 * The conditions a person is editing, including ones still missing a value, which do not apply yet. `onChange` gets
 * only the complete ones, or undefined when there are none. One condition is open for editing at a time.
 */
export function useConditionDrafts(
    value: PropertyCondition[],
    blankOperator: PropertyOperator,
    onChange: (value: PropertyCondition[] | undefined) => void
): {
    drafts: Draft[]
    editing: number | null
    edit: (id: number | null) => void
    editFirstIncomplete: () => void
    change: (draft: Draft) => void
    add: () => void
    remove: (id: number) => void
} {
    const nextId = useRef(0)
    const blank = (): Draft => ({ id: nextId.current++, operator: blankOperator })
    const draftsOf = (conditions: PropertyCondition[]): Draft[] =>
        conditions.length > 0 ? conditions.map((condition) => ({ ...condition, id: nextId.current++ })) : [blank()]
    const [drafts, setDrafts] = useState<Draft[]>(() => draftsOf(value))
    const [editing, edit] = useState<number | null>(drafts[drafts.length - 1].id)

    // A value changed from outside the editor, such as by another control, replaces the drafts. Otherwise the next
    // edit here would write the old conditions back over it.
    const valueKey = JSON.stringify(value)
    const [seenValueKey, setSeenValueKey] = useState(valueKey)
    if (valueKey !== seenValueKey) {
        setSeenValueKey(valueKey)
        if (valueKey !== JSON.stringify(completeOf(drafts))) {
            const next = draftsOf(value)
            setDrafts(next)
            edit(firstIncomplete(next))
        }
    }

    const update = (next: Draft[]): void => {
        setDrafts(next)
        const complete = completeOf(next)
        onChange(complete.length > 0 ? complete : undefined)
    }

    return {
        drafts,
        editing,
        edit,
        editFirstIncomplete: () => edit(firstIncomplete(drafts)),
        change: (changed) => update(drafts.map((draft) => (draft.id === changed.id ? changed : draft))),
        add: () => {
            const draft = blank()
            setDrafts([...drafts, draft])
            edit(draft.id)
        },
        remove: (id) => {
            const rest = drafts.filter((draft) => draft.id !== id)
            const next = rest.length > 0 ? rest : [blank()]
            update(next)
            if (id === editing || rest.length === 0) {
                edit(firstIncomplete(next))
            }
        },
    }
}
