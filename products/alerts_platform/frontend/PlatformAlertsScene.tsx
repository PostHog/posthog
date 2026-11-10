import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTableColumns, LemonTabs, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PlatformAlertConfigurationApi } from './generated/api.schemas'
import { OptionalTimeLabel } from './OptionalTimeLabel'
import { SOURCE_KINDS, configurationStatus, describeCondition, describeSchedule } from './platformAlertFormat'
import { PLATFORM_ALERTS_PAGE_SIZE, PlatformAlertsTab, platformAlertsLogic } from './platformAlertsLogic'
import { PlatformAlertStatusTag } from './PlatformAlertStatusTag'
import { PlatformAlertRouting } from './routing/PlatformAlertRouting'

export const scene: SceneExport = {
    component: PlatformAlertsScene,
    logic: platformAlertsLogic,
}

const COLUMNS: LemonTableColumns<PlatformAlertConfigurationApi> = [
    {
        title: 'Name',
        dataIndex: 'name',
        render: (_, configuration) => (
            <Link to={urls.platformAlert(configuration.id)} data-attr="platform-alerts-row-link">
                {configuration.name}
            </Link>
        ),
    },
    {
        title: 'Source',
        dataIndex: 'source_kind',
        render: (_, configuration) => SOURCE_KINDS[configuration.source_kind].label,
    },
    {
        title: 'Status',
        render: (_, configuration) => <PlatformAlertStatusTag status={configurationStatus(configuration)} />,
    },
    {
        title: 'Condition',
        render: (_, configuration) => describeCondition(configuration),
    },
    {
        title: 'Schedule',
        render: (_, configuration) => describeSchedule(configuration),
    },
    {
        title: 'Groups',
        render: (_, configuration) => configuration.alerts.length,
    },
    {
        title: 'Next check',
        dataIndex: 'next_check_at',
        render: (_, configuration) => <OptionalTimeLabel time={configuration.next_check_at} fallback="Not scheduled" />,
    },
]

export function PlatformAlertsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { configurationsPage, configurationsPageLoading, configurationsError, page, activeTab } =
        useValues(platformAlertsLogic)
    const { loadConfigurations, setPage, setActiveTab } = useActions(platformAlertsLogic)

    if (!featureFlags[FEATURE_FLAGS.PLATFORM_ALERTS]) {
        return <NotFound object="page" />
    }

    const configurations = configurationsError ? (
        <LemonBanner
            type="error"
            action={{
                children: 'Retry',
                onClick: () => loadConfigurations(),
                'data-attr': 'platform-alerts-retry',
            }}
        >
            Couldn't load alert configurations. Try again in a moment.
        </LemonBanner>
    ) : (
        <LemonTable
            dataSource={configurationsPage?.results ?? []}
            columns={COLUMNS}
            loading={configurationsPageLoading || configurationsPage === null}
            rowKey="id"
            emptyState="No alert configurations on the platform for this project yet."
            pagination={{
                controlled: true,
                pageSize: PLATFORM_ALERTS_PAGE_SIZE,
                currentPage: page,
                entryCount: configurationsPage?.count ?? 0,
                onForward: configurationsPage?.next ? () => setPage(page + 1) : undefined,
                onBackward: page > 1 ? () => setPage(page - 1) : undefined,
            }}
        />
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Platform alerts"
                description="Alert configurations evaluated by the shared alerts platform."
                resourceType={{ type: 'inbox' }}
            />
            {featureFlags[FEATURE_FLAGS.PLATFORM_ALERTS_ROUTING] ? (
                <LemonTabs<PlatformAlertsTab>
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    sceneInset
                    tabs={[
                        { key: 'alerts', label: 'Alerts', content: configurations },
                        { key: 'routing', label: 'Routing', content: <PlatformAlertRouting /> },
                    ]}
                />
            ) : (
                configurations
            )}
        </SceneContent>
    )
}
