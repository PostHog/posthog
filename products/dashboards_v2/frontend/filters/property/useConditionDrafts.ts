import { useRef, useState } from 'react'

import type { PropertyOperator } from '~/types'

import { type PropertyCondition, isCompleteCondition } from './propertyOperators'

export type Draft = PropertyCondition & {
    id: number
}

function firstIncomplete(drafts: Draft[]): number | null {
    return drafts.find((draft) => !isCompleteCondition(draft))?.id ?? null
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
    const nextId = useRef(value.length)
    const blank = (): Draft => ({ id: nextId.current++, operator: blankOperator })
    const [drafts, setDrafts] = useState<Draft[]>(() =>
        value.length > 0 ? value.map((condition, index) => ({ ...condition, id: index })) : [blank()]
    )
    const [editing, edit] = useState<number | null>(drafts[drafts.length - 1].id)

    const update = (next: Draft[]): void => {
        setDrafts(next)
        const complete = next.filter(isCompleteCondition).map(({ operator, value }) => ({ operator, value }))
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
