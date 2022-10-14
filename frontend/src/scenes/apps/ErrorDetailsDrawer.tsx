import { Card } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { appMetricsSceneLogic } from './appMetricsSceneLogic'
import { Drawer } from 'lib/components/Drawer'

export function ErrorDetailsDrawer(): JSX.Element {
    const { errorDetailsDrawerError, errorDetails, errorDetailsLoading } = useValues(appMetricsSceneLogic)
    const { closeErrorDetailsDrawer } = useActions(appMetricsSceneLogic)

    return (
        <Drawer
            visible={!!errorDetailsDrawerError}
            onClose={closeErrorDetailsDrawer}
            title={`Viewing error details: ${errorDetailsDrawerError}`}
            destroyOnClose
        >
            <pre>{JSON.stringify(errorDetails, null, 2)}</pre>
        </Drawer>
    )
}
