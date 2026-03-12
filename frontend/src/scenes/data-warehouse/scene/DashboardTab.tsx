import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { Dashboard } from 'scenes/dashboard/Dashboard'

import { DashboardPlacement } from '~/types'

import { dataWarehouseSceneLogic } from '../dataWarehouseSceneLogic'

export function DashboardTab(): JSX.Element {
    const { dataOpsDashboardId, dataOpsDashboardIdLoading } = useValues(dataWarehouseSceneLogic)

    if (dataOpsDashboardIdLoading || dataOpsDashboardId === null) {
        return (
            <div className="flex flex-col gap-4 mt-4">
                <LemonSkeleton className="h-48 w-full" />
                <LemonSkeleton className="h-48 w-full" />
            </div>
        )
    }

    return <Dashboard id={dataOpsDashboardId.toString()} placement={DashboardPlacement.DataOps} />
}
