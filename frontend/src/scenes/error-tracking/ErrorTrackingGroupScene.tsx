import './ErrorTracking.scss'

import { LemonDivider, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingActions } from './ErrorTrackingActions'
import { ErrorTrackingFilters } from './ErrorTrackingFilters'
import { ErrorGroupTab, errorTrackingGroupSceneLogic } from './errorTrackingGroupSceneLogic'
import { BreakdownsTab } from './groups/BreakdownsTab'
import { OverviewTab } from './groups/OverviewTab'

export const scene: SceneExport = {
    component: ErrorTrackingGroupScene,
    logic: errorTrackingGroupSceneLogic,
    paramsToProps: ({ params: { id: fingerprint } }): (typeof errorTrackingGroupSceneLogic)['props'] => ({
        fingerprint,
    }),
}

export function ErrorTrackingGroupScene(): JSX.Element {
    const { errorGroupTab } = useValues(errorTrackingGroupSceneLogic)
    const { setErrorGroupTab } = useActions(errorTrackingGroupSceneLogic)

    return (
        <div className="space-y-4">
            <ErrorTrackingFilters />
            <LemonDivider />
            <ErrorTrackingActions showOrder={false} />

            <LemonTabs
                activeKey={errorGroupTab}
                onChange={setErrorGroupTab}
                tabs={[
                    {
                        key: ErrorGroupTab.Overview,
                        label: 'Overview',
                        content: <OverviewTab />,
                    },
                    {
                        key: ErrorGroupTab.Breakdowns,
                        label: 'Breakdowns',
                        content: <BreakdownsTab />,
                    },
                ]}
            />
        </div>
    )
}
