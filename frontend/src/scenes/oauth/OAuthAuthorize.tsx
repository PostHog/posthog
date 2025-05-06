import { SceneExport } from '../sceneTypes'
import { oauthAuthorizeLogic } from './oauthAuthorizeLogic'

export const OAuthAuthorize = (): JSX.Element => {
    return <div>OAuthAuthorizeScene</div>
}

export const scene: SceneExport = {
    component: OAuthAuthorize,
    logic: oauthAuthorizeLogic,
}
