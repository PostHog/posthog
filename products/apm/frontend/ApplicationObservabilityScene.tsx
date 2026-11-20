import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconPauseFilled, IconPlayFilled, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { TracesAlertFromRowModals } from 'products/tracing/frontend/alerting/TracesAlertFromRowModals'
import type { TracesAlertFormType } from 'products/tracing/frontend/alerting/tracesAlertUtils'

import {
    ApplicationObservabilityTab,
    TIME_RANGE_LABELS,
    TimeRange,
    applicationObservabilityLogic,
} from './applicationObservabilityLogic'
import { DependenciesTab } from './DependenciesTab'
import { DeploymentsTab } from './DeploymentsTab'
import { EndpointsTab } from './EndpointsTab'
import { environmentOptions } from './environmentDisplay'
import { ServiceMapTab } from './ServiceMapTab'
import { ServicesTab } from './ServicesTab'
import { UsageTab } from './UsageTab'

export const scene: SceneExport = {
    component: ApplicationObservabilityScene,
    logic: applicationObservabilityLogic,
}

export function ApplicationObservabilityScene(): JSX.Element {
    const { environment, environments, timeRange, tab, paused, refreshing } = useValues(applicationObservabilityLogic)
    const { setEnvironment, setTimeRange, setTab, setPaused, refresh } = useActions(applicationObservabilityLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    // The platform API serves traces alerts only with both flags on.
    const alertsAvailable = !!(
        featureFlags[FEATURE_FLAGS.PLATFORM_ALERTS] && featureFlags[FEATURE_FLAGS.PLATFORM_ALERTS_SOURCE_TRACES]
    )
    // Held here, not in the row, so a refresh that drops the row keeps the draft open.
    const [alertDraft, setAlertDraft] = useState<TracesAlertFormType | null>(null)
    const closeAlertDraft = useCallback((): void => setAlertDraft(null), [])
    const onCreateAlert = alertsAvailable ? setAlertDraft : undefined

    return (
        <SceneContent>
            <SceneTitleSection
                name="Application observability"
                description="Service health from your spans, and how much each service sends across logs, traces, and metrics."
                resourceType={{ type: 'tracing' }}
            />
            <div className="flex flex-wrap items-center gap-2">
                {/* Usage counts every environment, so its tab has no environment picker. */}
                {tab !== 'usage' && (
                    <LemonSelect
                        size="small"
                        value={environment}
                        onChange={(value) => setEnvironment(value)}
                        options={environmentOptions(environments, environment)}
                        data-attr="apm-environment"
                    />
                )}
                <LemonSelect
                    size="small"
                    value={timeRange}
                    onChange={(value) => setTimeRange(value as TimeRange)}
                    options={(Object.keys(TIME_RANGE_LABELS) as TimeRange[]).map((value) => ({
                        value,
                        label: TIME_RANGE_LABELS[value],
                    }))}
                    data-attr="apm-time-range"
                />
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={refresh}
                    loading={refreshing}
                    tooltip="Refresh now"
                    data-attr="apm-refresh"
                />
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={paused ? <IconPlayFilled /> : <IconPauseFilled />}
                    onClick={() => setPaused(!paused)}
                    data-attr="apm-live-toggle"
                >
                    {paused ? 'Resume' : 'Pause'}
                </LemonButton>
                <span className="text-muted text-xs">
                    {paused ? 'Auto-refresh paused' : 'Refreshes every 5 minutes'}
                </span>
            </div>
            <LemonTabs<ApplicationObservabilityTab>
                activeKey={tab}
                onChange={setTab}
                tabs={[
                    { key: 'services', label: 'Services', content: <ServicesTab onCreateAlert={onCreateAlert} /> },
                    { key: 'endpoints', label: 'Endpoints', content: <EndpointsTab onCreateAlert={onCreateAlert} /> },
                    { key: 'map', label: 'Map', content: <ServiceMapTab /> },
                    { key: 'dependencies', label: 'Dependencies', content: <DependenciesTab /> },
                    { key: 'deployments', label: 'Deployments', content: <DeploymentsTab /> },
                    { key: 'usage', label: 'Usage', content: <UsageTab /> },
                ]}
                data-attr="apm-tabs"
            />
            {alertDraft !== null && <TracesAlertFromRowModals initialForm={alertDraft} onDone={closeAlertDraft} />}
        </SceneContent>
    )
}
