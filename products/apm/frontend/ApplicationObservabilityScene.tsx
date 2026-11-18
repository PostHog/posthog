import { useActions, useValues } from 'kea'

import { LemonSelect, LemonTabs } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    ApplicationObservabilityTab,
    TIME_RANGE_LABELS,
    TimeRange,
    applicationObservabilityLogic,
} from './applicationObservabilityLogic'
import { EndpointsTab } from './EndpointsTab'
import { ServiceMapTab } from './ServiceMapTab'
import { ServicesTab } from './ServicesTab'
import { UsageTab } from './UsageTab'

export const scene: SceneExport = {
    component: ApplicationObservabilityScene,
    logic: applicationObservabilityLogic,
}

export function ApplicationObservabilityScene(): JSX.Element {
    const { environments, resolvedEnvironment, timeRange, tab } = useValues(applicationObservabilityLogic)
    const { setEnvironment, setTimeRange, setTab } = useActions(applicationObservabilityLogic)

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
                        value={resolvedEnvironment}
                        onChange={(value) => setEnvironment(value)}
                        options={(environments.length ? environments : [resolvedEnvironment]).map((env) => ({
                            value: env,
                            label: env,
                        }))}
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
                <span className="text-muted text-xs">Refreshes every 5 minutes</span>
            </div>
            <LemonTabs<ApplicationObservabilityTab>
                activeKey={tab}
                onChange={setTab}
                tabs={[
                    { key: 'services', label: 'Services', content: <ServicesTab /> },
                    { key: 'endpoints', label: 'Endpoints', content: <EndpointsTab /> },
                    { key: 'map', label: 'Map', content: <ServiceMapTab /> },
                    { key: 'usage', label: 'Usage', content: <UsageTab /> },
                ]}
                data-attr="apm-tabs"
            />
        </SceneContent>
    )
}
