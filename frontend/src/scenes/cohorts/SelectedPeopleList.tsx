import { LemonSnack } from '@posthog/lemon-ui'

export interface SelectedPeopleListProps {
    people: Record<string, string | null>
    onRemove: (personId: string) => void
}

export function SelectedPeopleList({ people, onRemove }: SelectedPeopleListProps): JSX.Element | null {
    const entries = Object.entries(people)
    if (entries.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-y-1" data-attr="cohort-selected-persons">
            <h4 className="text-xs font-semibold uppercase opacity-60 mb-0">Selected people ({entries.length})</h4>
            <div className="flex flex-wrap gap-1">
                {entries.map(([personId, displayName]) => (
                    <LemonSnack key={personId} onClose={() => onRemove(personId)}>
                        {displayName || personId}
                    </LemonSnack>
                ))}
            </div>
        </div>
    )
}
