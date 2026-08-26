import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconFlask } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { superpowersLogic } from 'lib/components/Superpowers/superpowersLogic'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { CopyExperimentToProjectModal } from '../CopyExperimentToProjectModal'
import { DuplicateExperimentModal } from '../DuplicateExperimentModal'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { ExperimentActionsMenu } from './ExperimentActionsMenu'
import { FinishExperimentModal, PauseExperimentModal, ResumeExperimentModal } from './ExperimentModals'
import { ExperimentSceneMenuBar } from './ExperimentSceneMenuBar'
import { useExperimentActions } from './useExperimentActions'

export function PageHeaderCustom(): JSX.Element {
    const {
        experiment,
        isExperimentDraft,
        isExperimentRunning,
        isExperimentStopped,
        experimentLoading,
        launchExperimentLoading,
    } = useValues(experimentLogic)
    const { launchExperiment, updateExperiment, setHogfettiTrigger } = useActions(experimentLogic)
    const { isDuplicateExperimentModalOpen, isCopyToProjectModalOpen, isQuickSurveyModalOpen } = useValues(modalsLogic)
    const { openFinishExperimentModal, closeDuplicateExperimentModal, closeCopyToProjectModal, closeQuickSurveyModal } =
        useActions(modalsLogic)
    const actionSections = useExperimentActions()
    const { trigger, HogfettiComponent } = useHogfetti()

    useOnMountEffect(() => {
        setHogfettiTrigger(trigger)
    })

    const canEdit = userHasAccess(
        AccessControlResourceType.Experiment,
        AccessControlLevel.Editor,
        experiment.user_access_level
    )

    return (
        <>
            <ExperimentSceneMenuBar />
            <SceneTitleSection
                name={experiment?.name}
                description={null}
                resourceType={{
                    type: 'experiment',
                }}
                isLoading={experimentLoading}
                onNameChange={(name) => updateExperiment({ name })}
                onDescriptionChange={(description) => updateExperiment({ description })}
                canEdit={canEdit}
                renameDebounceMs={0}
                saveOnBlur
                actions={
                    <>
                        {experiment && isExperimentDraft && (
                            <div className="flex items-center">
                                <LemonButton
                                    type="primary"
                                    data-attr="launch-experiment"
                                    onClick={() => launchExperiment()}
                                    loading={launchExperimentLoading}
                                    size="small"
                                >
                                    Launch
                                </LemonButton>
                            </div>
                        )}
                        {experiment && isExperimentRunning && !isExperimentStopped && (
                            <>
                                <Tooltip title="Conclude this experiment and decide which variant to keep">
                                    <LemonButton
                                        type="primary"
                                        icon={<IconFlask />}
                                        onClick={() => openFinishExperimentModal()}
                                        size="small"
                                    >
                                        <b>End experiment</b>
                                    </LemonButton>
                                </Tooltip>
                                <FinishExperimentModal />
                            </>
                        )}
                        <ExperimentActionsMenu />
                    </>
                }
            />
            <HogfettiComponent />

            {experiment && (
                <ScenePanel>
                    <ScenePanelActionsSection>
                        {actionSections.map((section, index) => (
                            <Fragment key={section.key}>
                                {index > 0 && <LemonDivider />}
                                {section.items.map((item) => (
                                    <ButtonPrimitive
                                        key={item['data-attr'] ?? String(item.label)}
                                        menuItem
                                        variant={item.status === 'danger' ? 'danger' : 'default'}
                                        onClick={item.onClick}
                                        disabledReasons={
                                            item.disabledReason ? { [item.disabledReason]: true } : undefined
                                        }
                                        data-attr={item['data-attr']}
                                    >
                                        {item.icon}
                                        {item.label}
                                        {item.sideIcon && <span className="ml-auto">{item.sideIcon}</span>}
                                    </ButtonPrimitive>
                                ))}
                            </Fragment>
                        ))}
                    </ScenePanelActionsSection>
                    <ExperimentDebugToggle />
                </ScenePanel>
            )}
            {experiment && (
                <>
                    {/* Outside ScenePanel: the panel unmounts its children whenever no panel
                        element is registered, which would leave these modals' open state dangling. */}
                    <PauseExperimentModal />
                    <ResumeExperimentModal />
                    <DuplicateExperimentModal
                        isOpen={isDuplicateExperimentModalOpen}
                        onClose={() => closeDuplicateExperimentModal()}
                        experiment={experiment}
                    />
                    <CopyExperimentToProjectModal
                        isOpen={isCopyToProjectModalOpen}
                        onClose={() => closeCopyToProjectModal()}
                        experiment={experiment}
                    />
                </>
            )}
            <QuickSurveyModal
                context={{ type: QuickSurveyType.EXPERIMENT, experiment }}
                isOpen={isQuickSurveyModalOpen}
                onCancel={() => closeQuickSurveyModal()}
            />
        </>
    )
}

function ExperimentDebugToggle(): JSX.Element {
    const { superpowersEnabled } = useValues(superpowersLogic)
    const { showDebugPanel } = useValues(experimentLogic)
    const { toggleDebugPanel } = useActions(experimentLogic)

    if (!superpowersEnabled) {
        return <></>
    }

    return (
        <ScenePanelActionsSection>
            <LemonSwitch
                className="px-2 py-1"
                checked={showDebugPanel}
                onChange={toggleDebugPanel}
                fullWidth
                label="Debug panel"
            />
        </ScenePanelActionsSection>
    )
}
