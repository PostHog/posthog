import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { destinationsLogic } from './destinationsLogic'

export interface DestinationsTabProps {
    id: string
}

export function DestinationsTab({ id }: DestinationsTabProps): JSX.Element {
    const logic = destinationsLogic({ sourceId: id })
    const { destinations, destinationsLoading, attachedDestinationIds, savedDestinationIdsLoading, canSave } =
        useValues(logic)
    const { toggleDestination, save } = useActions(logic)

    if (destinationsLoading) {
        return <LemonSkeleton className="w-full h-32" />
    }

    if (destinations.length === 0) {
        return (
            <LemonBanner type="info">
                No destinations set up yet. Add one in project settings to sync these tables somewhere alongside the
                PostHog warehouse.
            </LemonBanner>
        )
    }

    return (
        <div className="deprecated-space-y-4">
            <p>
                Every table on this source syncs to the destinations selected here. A table with its own destinations
                set ignores this list.
            </p>

            <LemonTable
                dataSource={destinations}
                rowKey={(destination: ExternalDataDestinationApi) => destination.id}
                columns={[
                    {
                        title: '',
                        key: 'attached',
                        width: 0,
                        render: (_, destination: ExternalDataDestinationApi) => (
                            <LemonCheckbox
                                checked={attachedDestinationIds.includes(destination.id)}
                                onChange={() => toggleDestination(destination.id)}
                            />
                        ),
                    },
                    {
                        title: 'Name',
                        key: 'name',
                        render: (_, destination: ExternalDataDestinationApi) => destination.name,
                    },
                    {
                        title: 'Type',
                        key: 'type',
                        render: (_, destination: ExternalDataDestinationApi) => (
                            <LemonTag type={destination.is_posthog_warehouse ? 'highlight' : 'default'}>
                                {destination.type}
                            </LemonTag>
                        ),
                    },
                ]}
            />

            {attachedDestinationIds.length === 0 && (
                <LemonBanner type="warning">
                    Pick at least one destination. To stop syncing this data, turn off syncing on the tables instead.
                </LemonBanner>
            )}

            <LemonButton
                type="primary"
                onClick={save}
                loading={savedDestinationIdsLoading}
                disabledReason={canSave ? undefined : 'No changes to save'}
            >
                Save destinations
            </LemonButton>
        </div>
    )
}
