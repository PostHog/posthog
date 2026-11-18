import { useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'

import { oauthDeviceAuthorizeLogic } from './oauthDeviceAuthorizeLogic'
import { DeviceCodeForm } from './steps/DeviceCodeForm'
import { DeviceDecision } from './steps/DeviceDecision'
import { DeviceReview } from './steps/DeviceReview'

export const scene: SceneExport = {
    component: OAuthDeviceAuthorize,
    logic: oauthDeviceAuthorizeLogic,
}

export function OAuthDeviceAuthorize(): JSX.Element {
    const { deviceGrant, decision } = useValues(oauthDeviceAuthorizeLogic)

    if (decision) {
        return <DeviceDecision approved={decision === 'authorized'} />
    }

    if (!deviceGrant) {
        return <DeviceCodeForm />
    }

    return <DeviceReview deviceGrant={deviceGrant} />
}
