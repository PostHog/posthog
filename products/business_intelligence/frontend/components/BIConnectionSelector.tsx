import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { getConnectionOptionLabel } from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'

import { biSceneLogic } from '../biSceneLogic'

export function BIConnectionSelector({ tabId }: { tabId: string }): JSX.Element {
    const logic = biSceneLogic({ tabId })
    const { connectionId, connectionOptions, connectionOptionsLoading } = useValues(logic)
    const { selectConnection } = useActions(logic)

    return (
        <LemonSelect
            size="small"
            fullWidth
            className="min-w-0"
            truncateText={{ maxWidthClass: 'max-w-full' }}
            value={connectionId}
            onChange={selectConnection}
            loading={connectionOptionsLoading}
            options={[
                { value: null, label: 'PostHog warehouse' },
                ...(connectionOptions ?? []).map((source) => ({
                    value: source.id,
                    label: getConnectionOptionLabel(source),
                    disabledReason:
                        source.supports_hogql === false ? 'This connection only supports raw SQL' : undefined,
                })),
            ]}
        />
    )
}
