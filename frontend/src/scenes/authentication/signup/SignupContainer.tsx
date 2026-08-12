import { SceneExport } from 'scenes/sceneTypes'

import { GlassSignup } from './variants/glass/GlassSignup'

export const scene: SceneExport = {
    component: SignupContainer,
}

export function SignupContainer(): JSX.Element | null {
    return <GlassSignup />
}
