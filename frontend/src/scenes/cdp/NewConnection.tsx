import { SceneExport } from 'scenes/sceneTypes'
import { NewConnectionLogic } from './NewConnectionLogic'
import { useValues } from 'kea'

export const scene: SceneExport = {
    component: NewConnection,
    logic: NewConnectionLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id }),
}

export function NewConnection(): JSX.Element {
    const { connectionChoice } = useValues(NewConnectionLogic)
    return <>{JSON.stringify(connectionChoice)}</>
}
