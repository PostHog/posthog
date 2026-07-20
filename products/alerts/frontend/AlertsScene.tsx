import { useValues } from 'kea'
import { router } from 'kea-router'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { Alerts } from './views/Alerts'

export function AlertsScene(): JSX.Element {
    const { searchParams } = useValues(router)
    const alertId = typeof searchParams.alert_id === 'string' ? searchParams.alert_id : null

    return (
        <SceneContent>
            <SceneTitleSection
                name="Alerts"
                description="Monitor insight metrics and get notified when conditions are met."
                resourceType={{ type: 'inbox' }}
            />
            <Alerts alertId={alertId} />
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: AlertsScene,
    productKey: ProductKey.ALERTS,
}
