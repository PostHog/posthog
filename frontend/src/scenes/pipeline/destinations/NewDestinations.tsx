import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter } from 'kea-forms'
import { PayGateButton } from 'lib/components/PayGateMini/PayGateButton'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'

import { AvailableFeature, PipelineStage } from '~/types'

import { pipelineAccessLogic } from '../pipelineAccessLogic'
import { PipelineBackend } from '../types'
import { newDestinationsLogic } from './newDestinationsLogic'

export function DestinationOptionsTable(): JSX.Element {
    const hogFunctionsEnabled = !!useFeatureFlag('HOG_FUNCTIONS')
    const { loading, filteredDestinations, filters } = useValues(newDestinationsLogic)
    const { setFilters, openFeedbackDialog } = useActions(newDestinationsLogic)
    const { canEnableDestination } = useValues(pipelineAccessLogic)

    return (
        <div className="space-y-2">
            <PayGateMini feature={AvailableFeature.DATA_PIPELINES} />

            <div className="flex items-center gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    value={filters.search ?? ''}
                    onChange={(e) => setFilters({ search: e })}
                />
                <Link className="text-sm font-semibold" subtle onClick={() => openFeedbackDialog()}>
                    Can't find what you're looking for?
                </Link>
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
                        key: 'name',
                        sorter(a, b) {
                            return a.name.localeCompare(b.name)
                        },
                        render: function RenderName(_, target) {
                            return (
                                <LemonTableLink
                                    to={canEnableDestination(target) ? target.url : undefined}
                                    title={
                                        <>
                                            {target.name}
                                            {target.status === 'alpha' ? (
                                                <LemonTag type="danger">Experimental</LemonTag>
                                            ) : target.status === 'beta' ? (
                                                <LemonTag type="completion">Beta</LemonTag>
                                            ) : target.status === 'stable' ? (
                                                <LemonTag type="highlight">New</LemonTag> // Once Hog Functions are fully released we can remove the new label
                                            ) : target.status ? (
                                                <LemonTag type="highlight">
                                                    {capitalizeFirstLetter(target.status)}
                                                </LemonTag>
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
                            return canEnableDestination(target) ? (
                                <LemonButton
                                    type="primary"
                                    data-attr={`new-${PipelineStage.Destination}`}
                                    icon={<IconPlusSmall />}
                                    // Preserve hash params to pass config in
                                    to={target.url}
                                    fullWidth
                                >
                                    Create
                                </LemonButton>
                            ) : (
                                <span className="whitespace-nowrap">
                                    <PayGateButton feature={AvailableFeature.DATA_PIPELINES} type="secondary" />
                                </span>
                            )
                        },
                    },
                ]}
            />
        </div>
    )
}
