import { ListScopeChip } from './components/ListScopeChip'
import { ListScope, scopeLabel } from './listScopes'
import { PersonScopeChipHost } from './PersonScopeChipHost'

export interface ListScopeChipHostProps {
    scope: ListScope | null
    onClear: () => void
}

/** The chip of the scope a list is narrowed to, with a person named once they are read. */
export function ListScopeChipHost({ scope, onClear }: ListScopeChipHostProps): JSX.Element | null {
    if (!scope) {
        return null
    }
    return scope.kind === 'person' ? (
        <PersonScopeChipHost scope={scope} onClear={onClear} />
    ) : (
        <ListScopeChip scope={scope} label={scopeLabel(scope)} onClear={onClear} />
    )
}
