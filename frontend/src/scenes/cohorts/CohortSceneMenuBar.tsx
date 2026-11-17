import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import {
    IconClock,
    IconCopy,
    IconLetter,
    IconPlus,
    IconPlusSmall,
    IconRefresh,
    IconSend,
    IconTrash,
} from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cohortEditLogic } from 'scenes/cohorts/cohortEditLogic'
import {
    cohortBroadcastAudience,
    cohortBroadcastDisabledReason,
    urlForCohortWorkflow,
} from 'scenes/cohorts/cohortUtils'
import { openDeleteCohortDialog } from 'scenes/cohorts/DeleteCohortDialog'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { useAddToNotebookAction } from 'scenes/notebooks/useAddToNotebookAction'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { useTodayPeoplePinAction } from '~/layout/today/useTodayPeoplePinAction'
import { CohortType } from '~/types'

import {
    captureMessageAudienceClicked,
    messageAudienceAccessDisabledReason,
} from 'products/workflows/frontend/MessageAudience/messageAudience'
import { openMessageAudience } from 'products/workflows/frontend/MessageAudience/messageAudienceWarnings'

import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'

const RESOURCE_TYPE = 'cohort'

export function CohortSceneMenuBar({ id }: { id?: CohortType['id'] }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <CohortSceneMenuBarInner id={id} />
}

function CohortSceneMenuBarInner({ id }: { id?: CohortType['id'] }): JSX.Element | null {
    const peoplePinActions = useTodayPeoplePinAction()
    const logic = cohortEditLogic({ id })
    const { cohort, cohortLoading, hasAddUsersMenu } = useValues(logic)
    const { duplicateCohort, deleteCohort, restoreCohort, setCsvUploadModalOpen, submitCohort } = useActions(logic)
    const modalLogic = addPersonToCohortModalLogic({ id })
    const { showAddPersonToCohortModal } = useActions(modalLogic)
    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const cohortIdNumber = typeof cohort?.id === 'number' ? cohort.id : undefined
    const addToNotebookAction = useAddToNotebookAction(RESOURCE_TYPE, {
        notebookSelectButtonProps: {
            resource: { type: NotebookNodeType.Cohort, attrs: { id: cohortIdNumber } },
        },
    })
    const fileActions = useSceneFileActions(RESOURCE_TYPE, { section: 'project' })

    if (!cohort) {
        return null
    }

    const isNewCohort = cohort.id === 'new' || cohort.id === undefined
    const isDeleted = cohort.deleted

    const accessDisabledReason = messageAudienceAccessDisabledReason()
    const broadcastDisabledReason = cohortBroadcastDisabledReason(cohort) ?? accessDisabledReason
    const savingDisabledReason = cohortLoading ? 'Saving cohort...' : undefined

    const actions: SceneAction[] = [
        ...peoplePinActions,
        ...(!isNewCohort && cohortIdNumber !== undefined
            ? ([
                  {
                      group: 'file',
                      section: 'create',
                      type: 'submenu',
                      id: `${RESOURCE_TYPE}-menubar-create`,
                      label: 'Create',
                      icon: <IconPlusSmall />,
                      items: [
                          {
                              id: `${RESOURCE_TYPE}-menubar-send-broadcast`,
                              label: 'Email this cohort',
                              icon: <IconLetter />,
                              disabledReason: broadcastDisabledReason ?? undefined,
                              onSelect: () => {
                                  captureMessageAudienceClicked('cohort', 'broadcast')
                                  void openMessageAudience(cohortBroadcastAudience(cohort), 'broadcast')
                              },
                          },
                          {
                              id: `${RESOURCE_TYPE}-menubar-message-with-workflow`,
                              label: 'Build a custom workflow',
                              icon: <IconSend />,
                              disabledReason: accessDisabledReason ?? undefined,
                              onSelect: () => {
                                  captureMessageAudienceClicked('cohort', 'workflow')
                                  router.actions.push(urlForCohortWorkflow(cohort))
                              },
                          },
                          // Adding to notebooks is deprecated under the rail redesign.
                          ...(!todayRailNav ? [addToNotebookAction] : []),
                      ],
                  },
              ] satisfies SceneAction[])
            : []),
        ...fileActions,
        ...(!isNewCohort && canCopyToProject
            ? ([
                  {
                      group: 'file',
                      section: 'project',
                      id: `${RESOURCE_TYPE}-menubar-copy-to-project`,
                      label: 'Copy to another project',
                      icon: <IconCopy />,
                      onSelect: () => router.actions.push(urls.resourceTransfer('Cohort', cohort.id)),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!isNewCohort
            ? ([
                  {
                      group: 'file',
                      section: 'project',
                      id: `${RESOURCE_TYPE}-menubar-calculation-history`,
                      label: 'Calculation history',
                      icon: <IconClock />,
                      onSelect: () => router.actions.push(urls.cohortCalculationHistory(cohort.id)),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(isDeleted
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-restore`,
                      label: 'Restore',
                      icon: <IconRefresh />,
                      disabledReason: cohortLoading ? 'Wait for the cohort to finish loading' : undefined,
                      onSelect: () => restoreCohort(),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!isNewCohort && !isDeleted
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-delete`,
                      label: 'Delete',
                      icon: <IconTrash />,
                      destructive: true,
                      onSelect: () => {
                          openDeleteCohortDialog({
                              cohortId: cohort.id,
                              cohortName: cohort.name,
                              onConfirm: () => deleteCohort(),
                          })
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!isDeleted
            ? ([
                  ...(isNewCohort
                      ? ([
                            {
                                group: 'edit',
                                section: 'save',
                                id: `${RESOURCE_TYPE}-menubar-cancel`,
                                label: 'Cancel',
                                disabledReason: cohortLoading ? 'Wait for the cohort to finish saving' : undefined,
                                onSelect: () => router.actions.push(urls.cohorts()),
                                pinned: { order: 1, variant: 'secondary', dataAttr: 'cancel-cohort' },
                            },
                        ] satisfies SceneAction[])
                      : []),
                  {
                      group: 'edit',
                      section: 'save',
                      id: `${RESOURCE_TYPE}-menubar-save`,
                      label: 'Save',
                      disabledReason: savingDisabledReason,
                      onSelect: () => submitCohort(),
                      pinned: {
                          order: 2,
                          variant: 'primary',
                          render: () => (
                              <Button
                                  variant="primary"
                                  data-attr="save-cohort"
                                  type="submit"
                                  loading={cohortLoading}
                                  disabledReason={savingDisabledReason}
                                  form="cohort"
                              >
                                  Save
                              </Button>
                          ),
                      },
                  },
                  ...(hasAddUsersMenu
                      ? ([
                            {
                                group: 'edit',
                                section: 'add-users',
                                type: 'submenu',
                                id: `${RESOURCE_TYPE}-menubar-add-users`,
                                label: 'Add users',
                                icon: <IconPlus />,
                                items: [
                                    {
                                        id: `${RESOURCE_TYPE}-menubar-upload-csv`,
                                        label: 'Upload a CSV',
                                        icon: <IconPlus />,
                                        opensFloatingUi: true,
                                        onSelect: () => setCsvUploadModalOpen(true),
                                    },
                                    {
                                        id: `${RESOURCE_TYPE}-menubar-add-users-manually`,
                                        label: 'Add users manually',
                                        icon: <IconPlus />,
                                        opensFloatingUi: true,
                                        onSelect: showAddPersonToCohortModal,
                                    },
                                ],
                                pinned: { order: 3, variant: 'secondary', dataAttr: 'cohort-add-users-menu' },
                            },
                        ] satisfies SceneAction[])
                      : []),
                  {
                      group: 'edit',
                      section: 'duplicate',
                      id: `${RESOURCE_TYPE}-menubar-duplicate-dynamic`,
                      label: 'Duplicate as dynamic cohort',
                      icon: <IconCopy />,
                      disabledReason: isNewCohort
                          ? 'Save the cohort first'
                          : cohort.is_static === true
                            ? 'Cohort must be dynamic to duplicate'
                            : cohort.is_calculating
                              ? 'Cohort is still calculating'
                              : undefined,
                      onSelect: () => duplicateCohort(false),
                  },
                  {
                      group: 'edit',
                      section: 'duplicate',
                      id: `${RESOURCE_TYPE}-menubar-duplicate-static`,
                      label: 'Duplicate as static cohort',
                      icon: <IconCopy />,
                      disabledReason: isNewCohort
                          ? 'Save the cohort first'
                          : cohort.is_calculating
                            ? 'Cohort is still calculating'
                            : undefined,
                      onSelect: () => duplicateCohort(true),
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
