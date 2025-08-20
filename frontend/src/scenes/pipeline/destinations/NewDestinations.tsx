import { useActions, useValues } from 'kea'

import { IconMegaphone, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTable, Link } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { HogFunctionTypeType, PipelineStage, SidePanelTab } from '~/types'

import { DestinationTag } from './DestinationTag'
import { DestinationsFilters } from './DestinationsFilters'
import { destinationsFiltersLogic } from './destinationsFiltersLogic'
import { getDestinationDocPath, newDestinationsLogic } from './newDestinationsLogic'

export interface NewDestinationsProps {
    types: HogFunctionTypeType[]
}

export function NewDestinations({ types }: NewDestinationsProps): JSX.Element {
    return (
        <div className="deprecated-space-y-2">
            <DestinationsFilters types={types} hideShowPaused />
            <DestinationOptionsTable types={types} />
        </div>
    )
}

export function DestinationOptionsTable({ types }: NewDestinationsProps): JSX.Element {
    const { loading, filteredDestinations, hiddenDestinations } = useValues(newDestinationsLogic({ types }))
    const { resetFilters } = useActions(destinationsFiltersLogic({ types }))
    const { filters } = useValues(destinationsFiltersLogic({ types }))
    const { openSidePanel } = useActions(sidePanelStateLogic)

    // Filter out coming soon destinations unless search is active and feature flag is enabled
    const visibleDestinations = filteredDestinations.filter(
        (destination) => destination.status !== 'coming_soon' || (filters.search?.length ?? 0) > 0
    )

    return (
        <>
            <LemonTable
                dataSource={visibleDestinations}
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
                            if (target.status === 'coming_soon') {
                                return (
                                    <LemonTableLink
                                        onClick={() =>
                                            openSidePanel(
                                                SidePanelTab.Docs,
                                                `https://posthog.com/docs/cdp/destinations/${getDestinationDocPath(
                                                    target.url
                                                )}`
                                            )
                                        }
                                        title={
                                            <>
                                                {target.name}
                                                {target.status && <DestinationTag status={target.status} />}
                                            </>
                                        }
                                        description={target.description}
                                    />
                                )
                            }
                            return (
                                <LemonTableLink
                                    to={target.url}
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
                            if (target.status === 'coming_soon') {
                                return (
                                    <LemonButton
                                        type="primary"
                                        data-attr={`request-${PipelineStage.Destination}`}
                                        icon={<IconMegaphone />}
                                        className="whitespace-nowrap"
                                        onClick={() =>
                                            openSidePanel(
                                                SidePanelTab.Docs,
                                                `https://posthog.com/docs/cdp/destinations/${getDestinationDocPath(
                                                    target.url
                                                )}`
                                            )
                                        }
                                    >
                                        Notify me
                                    </LemonButton>
                                )
                            }
                            return (
                                <LemonButton
                                    type="primary"
                                    data-attr={`new-${PipelineStage.Destination}`}
                                    icon={<IconPlusSmall />}
                                    to={target.url}
                                >
                                    Create
                                </LemonButton>
                            )
                        },
                    },
                ]}
            />
            {hiddenDestinations.length > 0 && (
                <div className="text-secondary">
                    {hiddenDestinations.length} hidden. <Link onClick={() => resetFilters()}>Show all</Link>
                </div>
            )}
        </>
    )
}
