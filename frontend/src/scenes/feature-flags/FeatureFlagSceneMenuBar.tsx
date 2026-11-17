import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import type { ReactNode } from 'react'

import {
    IconArchive,
    IconCheck,
    IconCopy,
    IconPencil,
    IconPlusSmall,
    IconRewind,
    IconSend,
    IconTrash,
    IconX,
} from '@posthog/icons'

import { SceneTagsCombobox } from 'lib/components/Scenes/SceneTagsCombobox'
import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { NotebookNodeType } from 'scenes/notebooks/types'
import { useAddToNotebookAction } from 'scenes/notebooks/useAddToNotebookAction'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { isRulesV2EditableConfig } from 'products/feature_flags/frontend/featureFlagConfigFormat'

import { openFeatureFlagDeleteDialog } from './featureFlagDeleteDialog'
import { FeatureFlagEvaluationContextsCombobox } from './FeatureFlagEvaluationContextsCombobox'
import { featureFlagLogic } from './featureFlagLogic'

const RESOURCE_TYPE = 'feature_flag'

export const EVALUATION_CONTEXTS_UNAVAILABLE_DISABLED_REASON = "Evaluation contexts can't be changed on this flag yet."

interface FeatureFlagEditActions {
    saveLabel: string
    saveDisabledReason?: string | null
    saveDataAttr: string
    cancelDataAttr: string
    onSave: () => void
    onCancel: () => void
    /** The title's save button: a form submit or a button with a loading state. */
    renderSave: () => ReactNode
}

interface FeatureFlagViewSceneMenuBarProps {
    canCreateFlagCohort: boolean
    broadcastDisabledReason: string | null | undefined
    archiveDisabledReason: string | undefined
    deleteDisabledReason: string | undefined
    onGetFeedback: () => void
    onToggleArchived: () => void
}

/** The edit form and the rules v2 editor pass `editing`, and get only their save and cancel actions. */
type FeatureFlagSceneMenuBarProps = FeatureFlagViewSceneMenuBarProps | { editing: FeatureFlagEditActions }

export function FeatureFlagSceneMenuBar(props: FeatureFlagSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!enabled) {
        return null
    }
    return 'editing' in props ? (
        <FeatureFlagEditSceneMenuBarInner {...props.editing} />
    ) : (
        <FeatureFlagSceneMenuBarInner {...props} />
    )
}

function FeatureFlagEditSceneMenuBarInner({
    saveLabel,
    saveDisabledReason,
    saveDataAttr,
    cancelDataAttr,
    onSave,
    onCancel,
    renderSave,
}: FeatureFlagEditActions): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'edit',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-save`,
            label: saveLabel,
            icon: <IconCheck />,
            disabledReason: saveDisabledReason ?? undefined,
            onSelect: onSave,
            pinned: { order: 1, variant: 'primary', dataAttr: saveDataAttr, render: renderSave },
        },
        {
            group: 'edit',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-cancel`,
            label: 'Cancel',
            icon: <IconX />,
            onSelect: onCancel,
            pinned: { order: 1, variant: 'secondary', dataAttr: cancelDataAttr },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}

function FeatureFlagSceneMenuBarInner({
    canCreateFlagCohort,
    broadcastDisabledReason,
    archiveDisabledReason,
    deleteDisabledReason,
    onGetFeedback,
    onToggleArchived,
}: FeatureFlagViewSceneMenuBarProps): JSX.Element {
    const { featureFlag, configFormat, dependentFlags } = useValues(featureFlagLogic)
    const {
        createStaticCohort,
        findOrCreateBroadcastCohort,
        editFeatureFlag,
        deleteFeatureFlag,
        restoreFeatureFlag,
        saveTagsInline,
        saveEvaluationContextsInline,
    } = useActions(featureFlagLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const isV1Config = configFormat === 'v1'

    const { group: _group, ...addToNotebookItem } = useAddToNotebookAction(RESOURCE_TYPE, {
        notebookSelectButtonProps: featureFlag.id
            ? { resource: { type: NotebookNodeType.FeatureFlag, attrs: { id: featureFlag.id } } }
            : undefined,
    })
    const fileActions = useSceneFileActions(RESOURCE_TYPE, { section: 'project' })

    const canEditFlag = isV1Config || isRulesV2EditableConfig(featureFlag.filters, featureFlags)
    const editDisabledReason =
        getAccessControlDisabledReason(
            AccessControlResourceType.FeatureFlag,
            AccessControlLevel.Editor,
            featureFlag.user_access_level
        ) ?? undefined

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            type: 'submenu',
            id: `${RESOURCE_TYPE}-menubar-create`,
            label: 'Create',
            icon: <IconPlusSmall />,
            items: [
                // Adding to notebooks is deprecated under the rail redesign.
                ...(featureFlag.id && !todayRailNav ? [addToNotebookItem] : []),
                ...(canCreateFlagCohort
                    ? [
                          {
                              id: `${RESOURCE_TYPE}-menubar-create-cohort`,
                              label: 'Cohort',
                              icon: <IconPlusSmall />,
                              onSelect: () => createStaticCohort(),
                          },
                          {
                              id: `${RESOURCE_TYPE}-menubar-message-audience-broadcast`,
                              label: 'Broadcast',
                              icon: <IconSend />,
                              disabledReason: broadcastDisabledReason ?? undefined,
                              onSelect: () => findOrCreateBroadcastCohort(),
                          },
                      ]
                    : []),
                {
                    id: `${RESOURCE_TYPE}-menubar-create-survey`,
                    label: 'Survey',
                    icon: <IconPlusSmall />,
                    opensFloatingUi: true,
                    onSelect: onGetFeedback,
                },
            ],
        },
        ...fileActions,
        ...(!featureFlag.deleted
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: featureFlag.archived
                          ? `${RESOURCE_TYPE}-menubar-unarchive`
                          : `${RESOURCE_TYPE}-menubar-archive`,
                      label: featureFlag.archived ? 'Unarchive feature flag' : 'Archive feature flag',
                      icon: featureFlag.archived ? <IconRewind /> : <IconArchive />,
                      destructive: true,
                      disabledReason: archiveDisabledReason,
                      onSelect: onToggleArchived,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(configFormat !== 'unsupported'
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: featureFlag.deleted ? `${RESOURCE_TYPE}-menubar-restore` : `${RESOURCE_TYPE}-menubar-delete`,
                      label: featureFlag.deleted ? 'Restore feature flag' : 'Delete feature flag',
                      icon: featureFlag.deleted ? <IconRewind /> : <IconTrash />,
                      destructive: true,
                      disabledReason: deleteDisabledReason,
                      onSelect: () => {
                          if (featureFlag.deleted) {
                              restoreFeatureFlag(featureFlag)
                          } else {
                              openFeatureFlagDeleteDialog(
                                  featureFlag,
                                  () => deleteFeatureFlag(featureFlag),
                                  dependentFlags
                              )
                          }
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canEditFlag
            ? ([
                  {
                      group: 'edit',
                      id: `${RESOURCE_TYPE}-menubar-edit-flag`,
                      label: 'Edit',
                      icon: <IconPencil />,
                      disabledReason: editDisabledReason,
                      onSelect: () => editFeatureFlag(true),
                      pinned: {
                          order: 1,
                          variant: 'secondary',
                          // pinned: data-attr values are wire strings
                          dataAttr: isV1Config ? undefined : 'edit-rules-v2-flag',
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(isV1Config
            ? ([
                  {
                      group: 'edit',
                      id: `${RESOURCE_TYPE}-menubar-duplicate`,
                      label: 'Duplicate',
                      icon: <IconCopy />,
                      onSelect: () => router.actions.push(urls.featureFlagNew({ sourceId: featureFlag.id })),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'metadata',
            type: 'panel',
            id: `${RESOURCE_TYPE}-menubar-metadata`,
            label: 'Metadata',
            render: () => (
                <>
                    <SceneTagsCombobox
                        onSave={(updatedTags) => saveTagsInline(updatedTags)}
                        canEdit
                        tags={featureFlag.tags}
                        dataAttrKey={RESOURCE_TYPE}
                    />
                    {featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_TAGS] && (
                        <FeatureFlagEvaluationContextsCombobox
                            evaluationContexts={featureFlag.evaluation_contexts || []}
                            onSave={saveEvaluationContextsInline}
                            disabledReason={isV1Config ? null : EVALUATION_CONTEXTS_UNAVAILABLE_DISABLED_REASON}
                        />
                    )}
                </>
            ),
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
