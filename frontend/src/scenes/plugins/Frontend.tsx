import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { BuiltLogic, kea, LogicWrapper, useValues } from 'kea'
import { frontendPluginLogicType } from 'scenes/plugins/FrontendType'
import { urls } from 'scenes/urls'
import { FrontendPlugin } from '~/types'
import { Skeleton } from 'antd'
import { appsLogic } from 'scenes/appsLogic'

export const frontendPluginLogic = kea<frontendPluginLogicType>({
    path: ['scenes', 'plugins', 'Frontend'],
    connect: [appsLogic],
    props: {} as {
        id: number
    },
    key: (props) => props.id,
    selectors: {
        plugin: [() => [appsLogic.selectors.apps, (_, props) => props.id], (apps, id): FrontendPlugin => apps[id]],
        logic: [(s) => [s.plugin], (plugin): LogicWrapper | undefined => plugin?.logic],
        builtLogic: [(s) => [s.logic, (_, props) => props], (logic: any, props: any) => logic?.(props)],
        Component: [(s) => [s.plugin], (plugin: any) => plugin?.component],
        breadcrumbsSelector: [(s) => [s.builtLogic], (builtLogic) => builtLogic?.selectors.breadcrumbs],
        breadcrumbs: [
            (s) => [(state, props) => s.breadcrumbsSelector(state, props)?.(state, props), s.plugin],
            (breadcrumbs, plugin: FrontendPlugin) => {
                return (
                    breadcrumbs ?? [
                        {
                            name: plugin?.title || `App #${plugin?.id}`,
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
