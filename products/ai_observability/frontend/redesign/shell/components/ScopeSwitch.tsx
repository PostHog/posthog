import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { ShellScope, ShellScopeId } from '../shellNavigation'

export interface ScopeSwitchProps {
    scopes: readonly ShellScope[]
    activeScope: ShellScopeId | null
    onScopeChange: (scope: ShellScope) => void
}

export function ScopeSwitch({ scopes, activeScope, onScopeChange }: ScopeSwitchProps): JSX.Element {
    return (
        <LemonSegmentedButton
            className="self-start"
            size="small"
            value={activeScope ?? undefined}
            onChange={(id) => {
                const scope = scopes.find((candidate) => candidate.id === id)
                if (scope && scope.id !== activeScope) {
                    onScopeChange(scope)
                }
            }}
            options={scopes.map((scope) => ({
                value: scope.id,
                label: scope.label,
                // pinned: autocapture dashboards and tests select the options by this value
                'data-attr': `ai-observability-scope-${scope.id}`,
            }))}
        />
    )
}
