import { LogicWrapper } from 'kea'

export type SceneComponent = (params: { sceneId: string }) => JSX.Element

export interface LoadedScene {
    Component: SceneComponent
    logic?: LogicWrapper
    propsTransform?: (props: Record<string, string>) => Record<string, any>
}
