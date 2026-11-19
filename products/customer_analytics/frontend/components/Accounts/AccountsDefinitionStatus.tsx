import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { accountsColumnConfigLogic } from './accountsColumnConfigLogic'

export function AccountsDefinitionStatus(): JSX.Element | null {
    const {
        customPropertyDefinitionsLoading,
        relationshipDefinitionsLoading,
        customPropertyDefinitionsError,
        relationshipDefinitionsError,
    } = useValues(accountsColumnConfigLogic)
    const { ensureDefinitionsLoaded } = useActions(accountsColumnConfigLogic)
    const loading = customPropertyDefinitionsLoading || relationshipDefinitionsLoading
    if (customPropertyDefinitionsError || relationshipDefinitionsError) {
        return (
            <div role="alert" className="flex flex-wrap items-center gap-2 p-2">
                Could not load properties. Try again.
                <LemonButton size="small" onClick={ensureDefinitionsLoaded} loading={loading}>
                    Retry
                </LemonButton>
            </div>
        )
    }
    return loading ? (
        <div role="status" className="p-2 text-secondary">
            Loading properties…
        </div>
    ) : null
}
