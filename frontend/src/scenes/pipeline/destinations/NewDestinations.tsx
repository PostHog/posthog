import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTable, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'

import { PipelineStage } from '~/types'

import { PipelineBackend } from '../types'
import { newDestinationsLogic } from './newDestinationsLogic'

export function DestinationOptionsTable(): JSX.Element {
    const hogFunctionsEnabled = !!useFeatureFlag('HOG_FUNCTIONS')
    const { loading, filteredDestinations, filters } = useValues(newDestinationsLogic)
    const { setFilters } = useActions(newDestinationsLogic)

    return (
        <>
            <div className="flex items-center mb-2 gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    value={filters.search ?? ''}
                    onChange={(e) => setFilters({ search: e })}
                />
                <div className="flex-1" />
                <LemonSelect
                    type="secondary"
                    size="small"
                    options={
                        [
                            { label: 'All kinds', value: null },
                            hogFunctionsEnabled
                                ? { label: 'Realtime (new)', value: PipelineBackend.HogFunction }
                                : undefined,
                            { label: 'Realtime', value: PipelineBackend.Plugin },
                            { label: 'Batch exports', value: PipelineBackend.BatchExport },
                        ].filter(Boolean) as { label: string; value: PipelineBackend | null }[]
                    }
                    value={filters.kind}
                    onChange={(e) => setFilters({ kind: e ?? undefined })}
                />
            </div>
            <LemonTable
                dataSource={filteredDestinations}
                size="small"
                loading={loading}
                columns={[
                    {
                        title: 'App',
                        width: 0,
                        render: (_, target) => target.icon,
                    },
                    {
                        title: 'Name',
                        sticky: true,
                        render: function RenderName(_, target) {
                            return (
                                <LemonTableLink
                                    to={target.url}
                                    title={
                                        <>
                                            {target.name}
                                            {target.status === 'alpha' ? (
                                                <LemonTag type="caution">Experimental</LemonTag>
                                            ) : target.status === 'beta' ? (
                                                <LemonTag type="highlight">Beta</LemonTag>
                                            ) : target.status === 'stable' ? (
                                                <LemonTag type="breakdown">New</LemonTag> // Once Hog Functions are fully released we can remove the new label
                                            ) : undefined}
                                        </>
                                    }
                                    description={target.description}
                                />
                            )
                        },
                    },
                    {
                        title: 'Actions',
                        width: 100,
                        align: 'right',
                        render: function RenderActions(_, target) {
                            return (
                                <LemonButton
                                    type="primary"
                                    data-attr={`new-${PipelineStage.Destination}`}
                                    icon={<IconPlusSmall />}
                                    // Preserve hash params to pass config in
                                    to={target.url}
                                >
                                    Create
                                </LemonButton>
                            )
                        },
                    },
                ]}
            />
        </>
    )
}
