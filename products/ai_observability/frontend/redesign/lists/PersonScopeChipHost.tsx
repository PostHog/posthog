import { useValues } from 'kea'

import { ListScopeChip } from './components/ListScopeChip'
import { ListScope, scopeLabel } from './listScopes'
import { personScopeLabelLogic } from './personScopeLabelLogic'

export interface PersonScopeChipHostProps {
    scope: ListScope
    onClear: () => void
}

/** The scope chip of a list scoped to a person, named once the person is read, and by a short id until then. */
export function PersonScopeChipHost({ scope, onClear }: PersonScopeChipHostProps): JSX.Element {
    const { person } = useValues(personScopeLabelLogic({ personId: scope.value }))
    return <ListScopeChip scope={scope} label={person?.person.label ?? scopeLabel(scope)} onClear={onClear} />
}
