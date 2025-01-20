import { LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { LemonButton } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'
import { LemonRow } from '@posthog/lemon-ui'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneIcon } from 'lib/components/SceneDashboardChoice/SceneIcon'

import { dashboardsModel } from '~/models/dashboardsModel'

import {
    sceneDashboardChoiceModalLogic,
    SceneDashboardChoiceModalProps,
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
                <>
                    <LemonButton
                        type="secondary"
                        data-attr="close-scene-dashboard-choice-modal"
                        onClick={closeSceneDashboardChoiceModal}
                    >
                        Close
                    </LemonButton>
                </>
            }
        >
            {dashboardsLoading ? (
                <div className="space-y-2">
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
                    <div className="space-y-2 min-h-100">
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
