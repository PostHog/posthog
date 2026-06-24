import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconClock, IconCopy, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonDialog } from '@posthog/lemon-ui'

import { SceneMenuBarAddToNotebook } from 'lib/components/Scenes/SceneMenuBarAddToNotebook'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { urls } from 'scenes/urls'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from '~/layout/scenes/components/SceneMenuBar'
import { CohortType } from '~/types'

const RESOURCE_TYPE = 'cohort'

export function CohortSceneMenuBar({ id }: { id?: CohortType['id'] }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <CohortSceneMenuBarInner id={id} />
}

function CohortSceneMenuBarInner({ id }: { id?: CohortType['id'] }): JSX.Element | null {
    const logic = cohortEditLogic({ id })
    const { cohort, cohortLoading } = useValues(logic)
    const { duplicateCohort, deleteCohort, restoreCohort } = useActions(logic)
    const { canCopyToProject } = useValues(interProjectCopyLogic)

    if (!cohort) {
        return null
    }

    const isNewCohort = cohort.id === 'new' || cohort.id === undefined
    const isDeleted = cohort.deleted

    const cohortIdNumber = typeof cohort.id === 'number' ? cohort.id : undefined

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                {!isNewCohort && cohortIdNumber !== undefined && (
                    <>
                        <SceneMenuBarSubMenu label="Create">
                            <SceneMenuBarAddToNotebook
                                dataAttrKey={RESOURCE_TYPE}
                                notebookSelectButtonProps={{
                                    resource: {
                                        type: NotebookNodeType.Cohort,
                                        attrs: { id: cohortIdNumber },
                                    },
                                }}
                            />
                        </SceneMenuBarSubMenu>
                        <SceneMenuBarSeparator />
                    </>
                )}
                <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                {!isNewCohort && canCopyToProject && (
                    <SceneMenuBarItem
                        onClick={() => router.actions.push(urls.resourceTransfer('Cohort', cohort.id))}
                        data-attr={`${RESOURCE_TYPE}-menubar-copy-to-project`}
                    >
                        <IconCopy />
                        Copy to another project
                    </SceneMenuBarItem>
                )}
                {!isNewCohort && !cohort.is_static && (
                    <SceneMenuBarItem
                        onClick={() => router.actions.push(urls.cohortCalculationHistory(cohort.id))}
                        data-attr={`${RESOURCE_TYPE}-menubar-calculation-history`}
                    >
                        <IconClock />
                        Calculation history
                    </SceneMenuBarItem>
                )}
                {(isDeleted || !isNewCohort) && <SceneMenuBarSeparator />}
                {isDeleted && (
                    <SceneMenuBarItem
                        disabled={cohortLoading}
                        onClick={() => restoreCohort()}
                        data-attr={`${RESOURCE_TYPE}-menubar-restore`}
                    >
                        <IconRefresh />
                        Restore
                    </SceneMenuBarItem>
                )}
                {!isNewCohort && !isDeleted && (
                    <SceneMenuBarItem
                        variant="destructive"
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Delete cohort?',
                                description: `Are you sure you want to delete "${cohort.name}"?`,
                                primaryButton: {
                                    children: 'Delete',
                                    status: 'danger',
                                    onClick: () => deleteCohort(),
                                    size: 'small',
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                    type: 'tertiary',
                                    size: 'small',
                                },
                            })
                        }}
                        data-attr={`${RESOURCE_TYPE}-menubar-delete`}
                    >
                        <IconTrash />
                        Delete
                    </SceneMenuBarItem>
                )}
            </SceneMenuBarMenu>
            {!isDeleted && (
                <SceneMenuBarMenu label="Edit" dataAttr={`${RESOURCE_TYPE}-menubar-edit`}>
                    <SceneMenuBarItem
                        onClick={() => duplicateCohort(false)}
                        disabled={isNewCohort || cohort.is_static === true || (cohort.is_calculating ?? false)}
                        tooltip={
                            isNewCohort
                                ? 'Save the cohort first'
                                : cohort.is_static === true
                                  ? 'Cohort must be dynamic to duplicate'
                                  : cohort.is_calculating
                                    ? 'Cohort is still calculating'
                                    : undefined
                        }
                        data-attr={`${RESOURCE_TYPE}-menubar-duplicate-dynamic`}
                    >
                        <IconCopy />
                        Duplicate as dynamic cohort
                    </SceneMenuBarItem>
                    <SceneMenuBarItem
                        onClick={() => duplicateCohort(true)}
                        disabled={isNewCohort || (cohort.is_calculating ?? false)}
                        tooltip={
                            isNewCohort
                                ? 'Save the cohort first'
                                : cohort.is_calculating
                                  ? 'Cohort is still calculating'
                                  : undefined
                        }
                        data-attr={`${RESOURCE_TYPE}-menubar-duplicate-static`}
                    >
                        <IconCopy />
                        Duplicate as static cohort
                    </SceneMenuBarItem>
                </SceneMenuBarMenu>
            )}
        </SceneMenuBar>
    )
}
