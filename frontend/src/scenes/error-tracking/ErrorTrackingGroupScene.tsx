import './ErrorTracking.scss'

import { LemonDivider, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { base64Decode } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'

import ErrorTrackingFilters from './ErrorTrackingFilters'
import { ErrorGroupTab, errorTrackingGroupSceneLogic } from './errorTrackingGroupSceneLogic'
import { BreakdownsTab } from './groups/BreakdownsTab'
import { OverviewTab } from './groups/OverviewTab'

export const scene: SceneExport = {
    component: ErrorTrackingGroupScene,
    logic: errorTrackingGroupSceneLogic,
    paramsToProps: ({ params: { fingerprint } }): (typeof errorTrackingGroupSceneLogic)['props'] => ({
        fingerprint: JSON.parse(base64Decode(decodeURIComponent(fingerprint))),
    }),
}

export function ErrorTrackingGroupScene(): JSX.Element {
    const { errorGroupTab } = useValues(errorTrackingGroupSceneLogic)
    const { setErrorGroupTab } = useActions(errorTrackingGroupSceneLogic)

    return (
        <>
            <ErrorTrackingFilters.FilterGroup />
            <LemonDivider className="mt-2" />
            <ErrorTrackingFilters.Options showOrder={false} />

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
        </>
    )
}
