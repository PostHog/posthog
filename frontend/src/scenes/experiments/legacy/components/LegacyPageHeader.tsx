import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArchive, IconFlask, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider, Tooltip } from '@posthog/lemon-ui'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ScenePanel, ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import {
    canArchiveExperiment,
    confirmArchiveExperiment,
    confirmDeleteExperiment,
} from '~/scenes/experiments/experimentActions'
import { FinishExperimentModal } from '~/scenes/experiments/ExperimentView/components'
import { modalsLogic } from '~/scenes/experiments/modalsLogic'
import { AccessControlLevel, AccessControlResourceType, ExperimentStatus } from '~/types'

import { legacyExperimentLogic } from '../legacyExperimentLogic'

/**
 * @deprecated
 * This component is used to display the header of a legacy experiment.
 * For modern experiments, use the PageHeader component.
 */
export function LegacyPageHeader(): JSX.Element {
    const { experiment } = useValues(legacyExperimentLogic)
    const { archiveExperiment } = useActions(legacyExperimentLogic)
    const { currentProjectId } = useValues(projectLogic)

    const { openFinishExperimentModal } = useActions(modalsLogic)

    const canEdit = userHasAccess(
        AccessControlResourceType.Experiment,
        AccessControlLevel.Editor,
        experiment.user_access_level
    )
    const canArchive = canEdit && canArchiveExperiment(experiment)
    const canDelete = canEdit

    const handleArchive = (): void => confirmArchiveExperiment(() => archiveExperiment())
    const handleDelete = (): void =>
        confirmDeleteExperiment({
            projectId: currentProjectId,
            experiment,
            onDelete: () => router.actions.push(urls.experiments()),
        })

    const isExperimentRunning = experiment.status === ExperimentStatus.Running
    const isExperimentStopped = experiment.status === ExperimentStatus.Stopped

    return (
        <>
            <SceneTitleSection
                name={experiment?.name}
                description={null}
                resourceType={{
                    type: 'experiment',
                }}
                isLoading={false}
                canEdit={false}
                renameDebounceMs={0}
                saveOnBlur
                actions={
                    <>
                        {canArchive && (
                            <LemonButton type="secondary" status="danger" onClick={handleArchive} size="small">
                                <b>Archive</b>
                            </LemonButton>
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
                    </>
                }
            />

            {experiment && (
                <ScenePanel>
                    <ScenePanelActionsSection>
                        <LemonDivider />

                        {canArchive && (
                            <ButtonPrimitive menuItem data-attr="archive-experiment" onClick={handleArchive}>
                                <IconArchive /> Archive experiment
                            </ButtonPrimitive>
                        )}

                        {canDelete && (
                            <ButtonPrimitive
                                variant="danger"
                                menuItem
                                data-attr="delete-experiment"
                                onClick={handleDelete}
                            >
                                <IconTrash /> Delete experiment
                            </ButtonPrimitive>
                        )}
                    </ScenePanelActionsSection>
                </ScenePanel>
            )}
        </>
    )
}
