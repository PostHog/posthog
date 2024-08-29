import './ErrorTracking.scss'

import { LemonDivider } from '@posthog/lemon-ui'
import { base64Decode } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'

import ErrorTrackingFilters from './ErrorTrackingFilters'
import { errorTrackingGroupSceneLogic } from './errorTrackingGroupSceneLogic'
import { OverviewTab } from './groups/OverviewTab'

export const scene: SceneExport = {
    component: ErrorTrackingGroupScene,
    logic: errorTrackingGroupSceneLogic,
    paramsToProps: ({ params: { fingerprint } }): (typeof errorTrackingGroupSceneLogic)['props'] => ({
        fingerprint: JSON.parse(base64Decode(decodeURIComponent(fingerprint))),
    }),
}

export function ErrorTrackingGroupScene(): JSX.Element {
    return (
        <>
            <SessionPlayerModal />
            <ErrorTrackingFilters.FilterGroup />
            <LemonDivider className="mt-2" />
            <ErrorTrackingFilters.Options showOrder={false} />
            <div className="pt-4">
                <OverviewTab />
            </div>
        </>
    )
}
