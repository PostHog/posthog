import { LemonBanner, LemonDivider, LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneIcon } from 'lib/components/SceneDashboardChoice/SceneIcon'
import { IconSettings } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'
import { dashboardsModel } from '~/models/dashboardsModel'

import {
    sceneDashboardChoiceModalLogic,
    SceneDashboardChoiceModalProps,
    sceneDescription,
} from './sceneDashboardChoiceModalLogic'

export function SceneDashboardChoiceModal({ scene }: SceneDashboardChoiceModalProps): JSX.Element {
    const modalLogic = sceneDashboardChoiceModalLogic({ scene })
    const { isOpen, currentDashboardId, dashboards, searchTerm, activeSection } = useValues(modalLogic)
    const { closeSceneDashboardChoiceModal, setSceneDashboardChoice, setAlternateScene, setSearchTerm, toggleSection } =
        useActions(modalLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { currentTeam } = useValues(teamLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    const offerReplay = currentTeam?.session_recording_opt_in && scene === Scene.ProjectHomepage
    // TODO what about you set this and then disable session recording?

    const title =
        scene == Scene.ProjectHomepage ? (
            'Choose your homepage for this project'
        ) : (
            <>Select a default dashboard for {sceneDescription[scene]}</>
        )

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeSceneDashboardChoiceModal}
            title={title}
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
            <LemonSegmentedButton
                options={[
                    { label: 'Dashboards', value: 'dashboard' },
                    { label: 'Session Replay', value: 'replay' },
                ]}
                onChange={(newSelection) => toggleSection(newSelection)}
                value={activeSection}
                fullWidth={true}
            />
            <LemonDivider />
            {activeSection === 'dashboard' && (
                <div>
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
                                                <span className="text-default font-normal text-ellipsis">
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
                                            <LemonRow
                                                key={dashboard.id}
                                                fullWidth
                                                status="muted"
                                                className="dashboard-row"
                                            >
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
                </div>
            )}
            {activeSection === 'replay' && (
                <div>
                    {offerReplay ? (
                        <>
                            <LemonButton
                                type="primary"
                                data-attr="set-homepage-session-replay"
                                onClick={() => {
                                    setSceneDashboardChoice(null)
                                    setAlternateScene('replay/recent')
                                    closeSceneDashboardChoiceModal()
                                }}
                            >
                                Show recent session recordings as your home page
                            </LemonButton>
                        </>
                    ) : (
                        <LemonBanner
                            type="info"
                            action={{
                                type: 'secondary',
                                icon: <IconSettings />,
                                onClick: () => {
                                    openSettingsPanel({ sectionId: 'project-replay' })
                                    closeSceneDashboardChoiceModal()
                                },
                                children: 'Configure',
                            }}
                        >
                            Session recordings are currently disabled for this project.
                        </LemonBanner>
                    )}
                </div>
            )}
        </LemonModal>
    )
}
