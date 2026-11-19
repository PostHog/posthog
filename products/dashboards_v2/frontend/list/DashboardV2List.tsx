import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { InputGroup, InputGroupAddon, InputGroupInput, Skeleton } from '@posthog/quill'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { DashboardV2ListEmptyState } from './DashboardV2ListEmptyState'
import { DashboardV2ListLoadError } from './DashboardV2ListLoadError'
import { dashboardV2ListLogic } from './dashboardV2ListLogic'
import { DashboardV2ListSceneMenuBar } from './DashboardV2ListSceneMenuBar'
import { DashboardV2ListTable } from './DashboardV2ListTable'
import { NewDashboardV2Button } from './NewDashboardV2Button'
import { NewDashboardV2Dialog } from './NewDashboardV2Dialog'

export function DashboardV2List(): JSX.Element {
    const { dashboards, loadFailed, search, loadedSearch } = useValues(dashboardV2ListLogic)
    const { setSearch } = useActions(dashboardV2ListLogic)

    const firstRun = dashboards !== null && !dashboards.length && !loadedSearch

    return (
        <SceneContent>
            <DashboardV2ListSceneMenuBar />
            <SceneTitleSection
                name="Dashboards"
                description="Dashboards that keep their panels, layout and filters in one document."
                resourceType={{ type: 'dashboard' }}
                actions={
                    <div data-quill>
                        <NewDashboardV2Button />
                    </div>
                }
            />
            <div data-quill className="flex flex-col gap-3">
                {loadFailed ? (
                    <DashboardV2ListLoadError />
                ) : dashboards === null ? (
                    <Skeleton className="h-64 w-full" data-attr="dashboard-v2-list-skeleton" />
                ) : firstRun ? (
                    <DashboardV2ListEmptyState />
                ) : (
                    <>
                        <InputGroup size="sm" className="w-64 max-w-full">
                            <InputGroupAddon>
                                <IconSearch />
                            </InputGroupAddon>
                            <InputGroupInput
                                placeholder="Search dashboards"
                                aria-label="Search dashboards"
                                value={search}
                                onChange={(event) => setSearch(event.target.value)}
                                data-attr="dashboard-v2-search"
                            />
                        </InputGroup>
                        <DashboardV2ListTable dashboards={dashboards} />
                    </>
                )}
                <NewDashboardV2Dialog />
            </div>
        </SceneContent>
    )
}
