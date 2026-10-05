import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PlatformAlertConfigurationApi } from './generated/api.schemas'
import { SOURCE_KIND_LABELS, configurationStatus, describeCondition, describeSchedule } from './platformAlertFormat'
import { PLATFORM_ALERTS_PAGE_SIZE, platformAlertsLogic } from './platformAlertsLogic'
import { PlatformAlertStatusTag } from './PlatformAlertStatusTag'

export const scene: SceneExport = {
    component: PlatformAlertsScene,
    logic: platformAlertsLogic,
}

export function PlatformAlertsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { configurationsPage, configurationsPageLoading, configurationsError, page } = useValues(platformAlertsLogic)
    const { loadConfigurations, setPage } = useActions(platformAlertsLogic)

    if (!featureFlags[FEATURE_FLAGS.PLATFORM_ALERTS]) {
        return <NotFound object="page" />
    }

    const columns: LemonTableColumns<PlatformAlertConfigurationApi> = [
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
            render: (_, configuration) => SOURCE_KIND_LABELS[configuration.source_kind] ?? configuration.source_kind,
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
            render: (_, configuration) =>
                configuration.next_check_at ? (
                    <TZLabel time={configuration.next_check_at} />
                ) : (
                    <span className="text-secondary">Not scheduled</span>
                ),
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Platform alerts"
                description="Alert configurations evaluated by the shared alerts platform. Read only."
                resourceType={{ type: 'inbox' }}
            />
            {configurationsError && !configurationsPage ? (
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
                    columns={columns}
                    loading={configurationsPageLoading}
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
            )}
        </SceneContent>
    )
}
