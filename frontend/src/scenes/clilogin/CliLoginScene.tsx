import { IconRefresh } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
// import api from 'lib/api'
import { SceneExport } from 'scenes/sceneTypes'

import { CliLoginSceneLogic } from './CliLoginSceneLogic'

interface CliLoginSceneProps {
    code?: string
}

export const scene: SceneExport = {
    component: CliLoginScene,
    logic: CliLoginSceneLogic,
    paramsToProps: ({ params: { code } }: { params: CliLoginSceneProps }): CliLoginSceneProps => ({
        code: code || 'missing',
    }),
}

export function CliLoginScene(): JSX.Element {
    return (
        <div>
            <CliLoginPage />
        </div>
    )
}

export function CliLoginPage(): JSX.Element {
    // export function CliLoginPage({ code }: { code?: string }): JSX.Element {
    // const [getCode, setCode] = useState(code || 'missing');

    return (
        <div>
            <h1 className="page-title">CLI Login page</h1>
            <p>Click here to authorize the CLI.</p>
            <p>
                <LemonButton type="primary" icon={<IconRefresh />}>
                    Authorize
                </LemonButton>
            </p>
        </div>
    )
}
