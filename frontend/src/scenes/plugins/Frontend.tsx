import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { kea, useValues } from 'kea'
import { frontendPluginLogicType } from 'scenes/plugins/FrontendType'

export const frontendPluginLogic = kea<frontendPluginLogicType>({
    path: ['scenes', 'plugins', 'Frontend'],
    connect: [pluginsLogic],
    props: {} as {
        id: number
    },
    selectors: {
        plugin: [
            () => [pluginsLogic.selectors.frontendPlugins, (_, props) => props.id],
            (frontendPlugins, id) => frontendPlugins.find((p) => p.id === id),
        ],
        Component: [(s) => [s.plugin], (plugin) => plugin?.sidebar?.component],
    },
})

export function Frontend({
    id,
}: {
    id?: string
} = {}): JSX.Element {
    const { Component } = useValues(frontendPluginLogic)
    if (Component) {
        return <Component />
    }
    return <div>Frontend plugin {id} not loaded!</div>
}

export const scene: SceneExport = {
    component: Frontend,
    logic: frontendPluginLogic,
    paramsToProps: ({ params: { id } }) => ({ id: parseInt(id) ?? 0 }),
}
