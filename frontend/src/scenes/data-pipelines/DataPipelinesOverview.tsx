import { IconPlusSmall } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { useEffect } from 'react'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { urls } from 'scenes/urls'

import { PipelineTab } from '~/types'

import { nonHogFunctionsLogic } from './utils/nonHogFunctionsLogic'

function Section({
    title,
    to,
    children,
}: {
    title: string
    to: string
    description?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <div>
            <Link to={to}>
                <h2>{title}</h2>
            </Link>
            <div className="deprecated-space-y-2">{children}</div>
        </div>
    )
}

export function DataPipelinesOverview(): JSX.Element {
    const menuItems: LemonMenuItems = [
        {
            label: 'Source',
            to: urls.dataPipelinesNew('source'),
            'data-attr': 'data-warehouse-data-pipelines-overview-new-source',
        },
        { label: 'Transformation', to: urls.dataPipelinesNew('transformation') },
        { label: 'Destination', to: urls.dataPipelinesNew('destination') },
    ]

    const { hogFunctionPluginsDestinations, hogFunctionBatchExports } = useValues(nonHogFunctionsLogic)
    const { loadHogFunctionPluginsDestinations, loadHogFunctionBatchExports } = useActions(nonHogFunctionsLogic)

    useEffect(() => {
        loadHogFunctionPluginsDestinations()
        loadHogFunctionBatchExports()
    }, [])

    return (
        <>
            <PageHeader
                buttons={
                    <div className="flex items-center m-2 shrink-0">
                        <LemonMenu items={menuItems}>
                            <LemonButton
                                data-attr="new-pipeline-button"
                                icon={<IconPlusSmall />}
                                size="small"
                                type="primary"
                            >
                                New
                            </LemonButton>
                        </LemonMenu>
                    </div>
                }
            />
            <div className="deprecated-space-y-4">
                <FlaggedFeature flag="cdp-hog-sources">
                    <Section title="Event sources" to={urls.pipeline(PipelineTab.Sources)}>
                        <HogFunctionList logicKey="overview-data-sources" type="source_webhook" />
                    </Section>
                </FlaggedFeature>
                <Section title="Managed data warehouse sources" to={urls.pipeline(PipelineTab.Sources)}>
                    <DataWarehouseManagedSourcesTable />
                </Section>
                <Section title="Self-managed data warehouse sources" to={urls.pipeline(PipelineTab.Sources)}>
                    <DataWarehouseSelfManagedSourcesTable />
                </Section>
                <Section title="Transformations" to={urls.pipeline(PipelineTab.Transformations)}>
                    <p>Modify and enrich your incoming data. Only active transformations are shown here.</p>
                    <HogFunctionList logicKey="transformation" type="transformation" hideFeedback={true} />
                </Section>
                <Section title="Destinations" to={urls.pipeline(PipelineTab.Destinations)}>
                    <p>
                        Send your data to destinations in real time or with batch exports. Only active Destinations are
                        shown here.
                    </p>
                    <HogFunctionList
                        logicKey="destination"
                        type="destination"
                        hideFeedback={true}
                        manualFunctions={[
                            ...(hogFunctionPluginsDestinations ?? []),
                            ...(hogFunctionBatchExports ?? []),
                        ]}
                    />
                </Section>
            </div>
        </>
    )
}
