import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PayGateButton } from 'lib/components/PayGateMini/PayGateButton'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'

import { AvailableFeature, PipelineStage } from '~/types'

import { pipelineAccessLogic } from '../pipelineAccessLogic'
import { DestinationsFilters } from './DestinationsFilters'
import { DestinationTag } from './DestinationTag'
import { newDestinationsLogic } from './newDestinationsLogic'

export function NewDestinations(): JSX.Element {
    return (
        <div className="space-y-2">
            <PayGateMini feature={AvailableFeature.DATA_PIPELINES} />
            <DestinationsFilters forceFilters={{ showPaused: false }} />
            <DestinationOptionsTable />
        </div>
    )
}

export function DestinationOptionsTable(): JSX.Element {
    const { loading, filteredDestinations } = useValues(newDestinationsLogic)
    const { canEnableDestination } = useValues(pipelineAccessLogic)

    return (
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
                                        {target.status && <DestinationTag status={target.status} />}
                                    </>
                                }
                                description={target.description}
                            />
                        )
                    },
                },
                {
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
    )
}
