import { Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { errorTrackingGroupSceneLogic } from './errorTrackingGroupSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingGroupScene,
    logic: errorTrackingGroupSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof errorTrackingGroupSceneLogic)['props'] => ({
        id,
    }),
}

export function ErrorTrackingGroupScene(): JSX.Element {
    const { eventProperties, eventPropertiesLoading } = useValues(errorTrackingGroupSceneLogic)

    return eventPropertiesLoading ? (
        <Spinner />
    ) : eventProperties && eventProperties.length > 0 ? (
        <ErrorDisplay eventProperties={eventProperties[0]} />
    ) : (
        <NotFound object="exception" />
    )
}
