import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { BuiltLogic, kea, LogicWrapper, useValues } from 'kea'
import { frontendPluginLogicType } from 'scenes/plugins/FrontendType'
import { urls } from 'scenes/urls'
import { FrontendPlugin } from '~/types'
import { Skeleton } from 'antd'

export const frontendPluginLogic = kea<frontendPluginLogicType>({
    path: ['scenes', 'plugins', 'Frontend'],
    connect: [pluginsLogic],
    props: {} as {
        id: number
    },
    key: (props) => props.id,
    selectors: {
        plugin: [
            () => [pluginsLogic.selectors.frontendPlugins, (_, props) => props.id],
            (frontendPlugins, id) => frontendPlugins.find((p) => p.id === id),
        ],
        scene: [(s) => [s.plugin], (plugin) => plugin?.scene],
        logic: [(s) => [s.scene], (scene: any): LogicWrapper => scene?.logic],
        builtLogic: [(s) => [s.logic, (_, props) => props], (logic: any, props: any) => logic?.(props)],
        Component: [(s) => [s.scene], (scene: any) => scene?.component],
        breadcrumbsSelector: [(s) => [s.builtLogic], (builtLogic) => builtLogic?.selectors.breadcrumbs],
        breadcrumbs: [
            (s) => [(state, props) => s.breadcrumbsSelector(state, props)?.(state, props), s.plugin],
            (breadcrumbs, plugin: FrontendPlugin) => {
                return (
                    breadcrumbs ?? [
                        {
                            name: plugin?.scene?.title || `App ${plugin?.id}`,
                        },
                    ]
                )
            },
        ],
    },
    subscriptions: ({ cache }: any) => ({
        builtLogic: (builtLogic: BuiltLogic) => {
            cache.unmount?.()
            cache.unmount = builtLogic?.mount()
        },
    }),
})

export function Frontend({
    id,
}: {
    id?: string
} = {}): JSX.Element {
    const props = { id: parseInt(id || '0') ?? 0, url: id ? urls.frontendPlugin(id) : '' }

    const { Component } = useValues(frontendPluginLogic(props))
    if (Component) {
        return <Component {...props} />
    }
    return (
        <div style={{ marginTop: 20 }}>
            <Skeleton />
        </div>
    )
}

export const scene: SceneExport = {
    component: Frontend,
    logic: frontendPluginLogic,
    paramsToProps: ({ params: { id } }) => ({ id: parseInt(id) ?? 0, url: id ? urls.frontendPlugin(id) : '' }),
}
