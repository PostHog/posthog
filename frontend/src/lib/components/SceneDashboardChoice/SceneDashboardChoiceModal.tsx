import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { SceneIcon } from 'lib/components/SceneDashboardChoice/SceneIcon'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'

import {
    SceneDashboardChoiceModalProps,
    sceneDashboardChoiceModalLogic,
    sceneDescription,
} from './sceneDashboardChoiceModalLogic'

export function SceneDashboardChoiceModal({ scene }: SceneDashboardChoiceModalProps): JSX.Element {
    const modalLogic = sceneDashboardChoiceModalLogic({ scene })
    const { isOpen, currentDashboardId, dashboards, searchTerm } = useValues(modalLogic)
    const { closeSceneDashboardChoiceModal, setSceneDashboardChoice, setSearchTerm } = useActions(modalLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeSceneDashboardChoiceModal}
            title={<>Select a default dashboard for {sceneDescription[scene]}</>}
            footer={
                <div className={cn('flex gap-2 w-full', currentDashboardId ? 'justify-between' : 'justify-end')}>
                    {currentDashboardId ? (
                        <LemonButton
                            type="secondary"
                            data-attr="scene-dashboard-choice-new-tab"
                            onClick={() => {
                                setSceneDashboardChoice(null)
                                setSearchTerm('')
                                closeSceneDashboardChoiceModal()
                            }}
                        >
                            Reset to "new tab"
                        </LemonButton>
                    ) : null}
                    <LemonButton
                        type="secondary"
                        data-attr="close-scene-dashboard-choice-modal"
                        onClick={closeSceneDashboardChoiceModal}
                    >
                        Close
                    </LemonButton>
                </div>
            }
        >
            {dashboardsLoading ? (
                <div className="deprecated-space-y-2">
                    <LemonSkeleton.Row repeat={4} />
                </div>
            ) : (
                <>
                    <LemonInput
                        type="search"
                        placeholder="Search for dashboards"
                        onChange={setSearchTerm}
                        value={searchTerm ?? undefined}
                        fullWidth={true}
                        allowClear={true}
                        className="mb-4"
                    />
                    <LemonDivider />
                    <div className="deprecated-space-y-2 min-h-100">
                        {dashboards.map((dashboard) => {
                            const isCurrentChoice = dashboard.id === currentDashboardId
                            const rowContents = (
                                <div className="flex flex-1 items-center justify-between overflow-hidden">
                                    <div className="flex-1 flex flex-col justify-center overflow-hidden">
                                        <strong>{dashboard.name}</strong>
                                        <span className="text-text-3000 font-normal text-ellipsis">
                                            {dashboard.description}
                                        </span>
                                    </div>
                                    {isCurrentChoice ? (
                                        <>
                                            <SceneIcon scene={scene} size="small" /> <span>Default</span>
                                        </>
                                    ) : (
                                        <strong className="set-default-text">Set as default</strong>
                                    )}
                                </div>
                            )
                            if (isCurrentChoice) {
                                return (
                                    <LemonRow key={dashboard.id} fullWidth status="muted" className="dashboard-row">
                                        {rowContents}
                                    </LemonRow>
                                )
                            }
                            return (
                                <LemonButton
                                    key={dashboard.id}
                                    fullWidth
                                    className="dashboard-row"
                                    onClick={() => {
                                        setSceneDashboardChoice(dashboard.id)
                                        setSearchTerm('')
                                        closeSceneDashboardChoiceModal()
                                        router.actions.replace(urls.projectHomepage())
                                    }}
                                >
                                    {rowContents}
                                </LemonButton>
                            )
                        })}
                    </div>
                </>
            )}
        </LemonModal>
    )
}
