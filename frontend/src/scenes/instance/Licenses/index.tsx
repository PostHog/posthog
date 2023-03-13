import { useEffect } from 'react'
import { licenseLogic } from './licenseLogic'
import { useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { billingV2Logic } from 'scenes/billing/billingV2Logic'

export const scene: SceneExport = {
    component: Licenses,
    logic: licenseLogic,
}

export function Licenses(): JSX.Element {
    const { billingVersion } = useValues(billingV2Logic)

    useEffect(() => {
        // Always go to the unified billing page
        router.actions.push(urls.organizationBilling())
    }, [billingVersion])

    return <div>{/* silence is golden */}</div>
}
