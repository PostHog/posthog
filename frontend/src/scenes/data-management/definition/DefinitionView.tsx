import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { definitionLogic, DefinitionLogicProps } from 'scenes/data-management/definition/definitionLogic'

export const scene: SceneExport = {
    component: DefinitionView,
    logic: definitionLogic,
    paramsToProps: ({ params: { id } }): typeof definitionLogic['props'] => ({
        id,
    }),
}

export function DefinitionView({ id }: DefinitionLogicProps = {}): JSX.Element {
    return <div>{id}</div>
}
