import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { MetricsScene } from 'products/metrics/frontend/MetricsScene'
import TracingScene from 'products/tracing/frontend/TracingScene'

import { LogsScene } from '../../logs/frontend/LogsScene'
import { ApmSceneTab, apmSceneLogic } from './apmSceneLogic'

export const scene: SceneExport = {
    component: ApmScene,
    logic: apmSceneLogic,
}

const APM_TABS: { key: ApmSceneTab; label: string; 'data-attr': string }[] = [
    { key: 'logs', label: 'Logs', 'data-attr': 'apm-tab-logs' },
    { key: 'traces', label: 'Traces', 'data-attr': 'apm-tab-traces' },
    { key: 'metrics', label: 'Metrics', 'data-attr': 'apm-tab-metrics' },
]

/**
 * One product, three facets. The facet scenes each bring their own `SceneContent` and title, so
 * this shell contributes only the switcher above them rather than a second layer of scene chrome.
 */
export function ApmScene(): JSX.Element {
    const { activeTab } = useValues(apmSceneLogic)
    const { setActiveTab } = useActions(apmSceneLogic)

    return (
        <>
            <LemonTabs<ApmSceneTab> activeKey={activeTab} onChange={setActiveTab} tabs={APM_TABS} sceneInset />
            {activeTab === 'logs' && <LogsScene />}
            {activeTab === 'traces' && <TracingScene />}
            {activeTab === 'metrics' && <MetricsScene />}
        </>
    )
}
