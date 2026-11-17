import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import type { ReactNode } from 'react'

import {
    IconArchive,
    IconCheck,
    IconCode,
    IconCopy,
    IconDownload,
    IconGlobe,
    IconInfo,
    IconMessage,
    IconPause,
    IconPencil,
    IconPlay,
    IconPlusSmall,
    IconSend,
    IconTrash,
    IconMagicWand,
    IconX,
} from '@posthog/icons'

import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { organizationLogic } from 'scenes/organizationLogic'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { SurveyFeedbackButton } from 'scenes/surveys/components/SurveyFeedbackButton'
import {
    SURVEY_FOLLOW_UP_WORKFLOW_LABEL,
    startSurveyFollowUpWorkflow,
} from 'scenes/surveys/components/SurveyFollowUpWorkflowButton'
import {
    canDeleteSurvey,
    openArchiveSurveyDialog,
    openDeleteSurveyDialog,
    openResumeSurveyDialog,
    openStopSurveyDialog,
} from 'scenes/surveys/surveyDialogs'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyStatus, isSurveyDraft, surveysLogic } from 'scenes/surveys/surveysLogic'
import { QuillSurveyStatusAction } from 'scenes/surveys/SurveyViewRedesign/QuillSurveyStatusAction'
import { useSurveyResponsesExport } from 'scenes/surveys/SurveyViewRedesign/SurveySidebar'
import { canUseSurveyWizard } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType, ExporterFormat, ProgressStatus, Survey } from '~/types'

import { messageAudienceAccessDisabledReason } from 'products/workflows/frontend/MessageAudience/messageAudience'

import { NEW_SURVEY } from './constants'

const RESOURCE_TYPE = 'survey'
// pinned: the feedback survey's selector targets this element id
const FEEDBACK_BUTTON_ID = 'surveys-page-feedback-button'

type SurveyViewSceneMenuBarProps = {
    onOpenSqlHelper: () => void
    onOpenDetails: () => void
}

type SurveyEditActions = {
    saveLabel: string
    saveDisabledReason?: string
    /** The survey is loading or saving. */
    busy: boolean
    onSave: () => void
    onCancel: () => void
    /** The title's save button, which submits the survey form. */
    renderSave: () => ReactNode
    onOpenGuidedEditor?: () => void
    onConvertToHosted?: () => void
}

/** The edit form passes `editing`, and gets only its editor actions. */
type SurveySceneMenuBarProps = SurveyViewSceneMenuBarProps | { editing: SurveyEditActions }

export function SurveySceneMenuBar(props: SurveySceneMenuBarProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return 'editing' in props ? (
        <SurveyEditSceneMenuBarInner {...props.editing} />
    ) : (
        <SurveySceneMenuBarInner {...props} />
    )
}

function SurveyEditSceneMenuBarInner({
    saveLabel,
    saveDisabledReason,
    busy,
    onSave,
    onCancel,
    renderSave,
    onOpenGuidedEditor,
    onConvertToHosted,
}: SurveyEditActions): JSX.Element {
    const busyReason = busy ? 'The survey is loading' : undefined
    const actions: SceneAction[] = [
        {
            group: 'edit',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-save`,
            label: saveLabel,
            icon: <IconCheck />,
            disabledReason: busyReason ?? saveDisabledReason,
            onSelect: onSave,
            pinned: { order: 1, variant: 'primary', dataAttr: 'save-survey', render: renderSave },
        },
        {
            group: 'edit',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-cancel`,
            label: 'Cancel',
            icon: <IconX />,
            disabledReason: busyReason,
            onSelect: onCancel,
            // pinned: data-attr values are wire strings
            pinned: { order: 1, variant: 'secondary', dataAttr: 'cancel-survey' },
        },
        ...(onOpenGuidedEditor
            ? ([
                  {
                      group: 'edit',
                      section: 'editor',
                      id: `${RESOURCE_TYPE}-menubar-guided-editor`,
                      label: 'Guided editor',
                      icon: <IconMagicWand />,
                      onSelect: onOpenGuidedEditor,
                      pinned: { order: 2, variant: 'secondary', dataAttr: 'switch-to-wizard' },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(onConvertToHosted
            ? ([
                  {
                      group: 'edit',
                      section: 'editor',
                      id: `${RESOURCE_TYPE}-menubar-convert-to-hosted`,
                      label: 'Convert to hosted',
                      icon: <IconGlobe />,
                      opensFloatingUi: true,
                      onSelect: onConvertToHosted,
                      pinned: { order: 3, variant: 'secondary', dataAttr: 'convert-to-hosted-survey' },
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}

function SurveySceneMenuBarInner({ onOpenSqlHelper, onOpenDetails }: SurveyViewSceneMenuBarProps): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { archiveSurvey, editingSurvey, stopSurvey, resumeSurvey } = useActions(surveyLogic)
    const { preferredEditor } = useValues(surveysLogic)
    const { deleteSurvey, duplicateSurvey, setSurveyToDuplicate } = useActions(surveysLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { push } = useActions(router)
    const { disabledReason: exportDisabledReason, exportResponses } = useSurveyResponsesExport()
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const fileActions = useSceneFileActions(RESOURCE_TYPE, { section: 'project' })

    const savedSurveyId = survey.id !== NEW_SURVEY.id ? survey.id : null
    const hasMultipleProjects = !!(currentOrganization?.teams && currentOrganization.teams.length > 1)
    const isDraft = isSurveyDraft(survey)
    const status = getSurveyStatus(survey)
    const followUpDisabledReason = messageAudienceAccessDisabledReason() ?? undefined
    const editorDisabledReason =
        getAccessControlDisabledReason(
            AccessControlResourceType.Survey,
            AccessControlLevel.Editor,
            survey.user_access_level
        ) ?? undefined
    const opensWizard = canUseSurveyWizard(survey) && preferredEditor === 'guided'
    // Drafts launch from the review's launch bar, so they get no stop or resume.
    const showStatusAction = status !== ProgressStatus.Draft && !survey.archived
    const isComplete = status === ProgressStatus.Complete

    const actions: SceneAction[] = [
        ...(savedSurveyId
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
                              id: `${RESOURCE_TYPE}-menubar-follow-up-workflow`,
                              label: SURVEY_FOLLOW_UP_WORKFLOW_LABEL,
                              icon: <IconSend />,
                              disabledReason: followUpDisabledReason,
                              onSelect: () => startSurveyFollowUpWorkflow(savedSurveyId),
                          },
                      ],
                  },
              ] satisfies SceneAction[])
            : []),
        ...fileActions,
        ...(canCopyToProject && savedSurveyId
            ? ([
                  {
                      group: 'file',
                      section: 'project',
                      id: `${RESOURCE_TYPE}-menubar-copy-to-project`,
                      label: 'Copy to another project',
                      icon: <IconCopy />,
                      onSelect: () => push(urls.resourceTransfer('Survey', savedSurveyId)),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!isDraft
            ? ([
                  {
                      group: 'file',
                      section: 'project',
                      id: `${RESOURCE_TYPE}-menubar-export-csv`,
                      label: 'Export responses as CSV',
                      icon: <IconDownload />,
                      disabledReason: exportDisabledReason ?? undefined,
                      onSelect: () => exportResponses(ExporterFormat.CSV),
                  },
                  {
                      group: 'file',
                      section: 'project',
                      id: `${RESOURCE_TYPE}-menubar-export-xlsx`,
                      label: 'Export responses as Excel',
                      icon: <IconDownload />,
                      disabledReason: exportDisabledReason ?? undefined,
                      onSelect: () => exportResponses(ExporterFormat.XLSX),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(!survey.archived
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-archive`,
                      label: 'Archive',
                      icon: <IconArchive />,
                      destructive: true,
                      disabledReason: editorDisabledReason,
                      onSelect: () => openArchiveSurveyDialog(survey, archiveSurvey),
                  },
              ] satisfies SceneAction[])
            : []),
        ...(canDeleteSurvey(survey)
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-delete`,
                      label: 'Delete permanently',
                      icon: <IconTrash />,
                      destructive: true,
                      disabledReason: editorDisabledReason,
                      onSelect: () => openDeleteSurveyDialog(survey, () => deleteSurvey(survey.id)),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'edit',
            id: `${RESOURCE_TYPE}-menubar-edit-survey`,
            label: 'Edit',
            icon: <IconPencil />,
            disabledReason: editorDisabledReason,
            onSelect: () => (opensWizard ? push(urls.surveyWizard(survey.id)) : editingSurvey(true)),
            pinned: { order: 2, variant: 'secondary', dataAttr: 'edit-survey' },
        },
        {
            group: 'edit',
            id: `${RESOURCE_TYPE}-menubar-duplicate`,
            label: 'Duplicate',
            icon: <IconCopy />,
            onSelect: () => {
                const existingSurvey = survey as Survey
                if (hasMultipleProjects) {
                    setSurveyToDuplicate(existingSurvey)
                } else {
                    duplicateSurvey(existingSurvey)
                }
            },
        },
        ...(!isDraft
            ? ([
                  {
                      group: 'edit',
                      id: `${RESOURCE_TYPE}-menubar-sql-query`,
                      label: 'SQL query',
                      icon: <IconCode />,
                      opensFloatingUi: true,
                      onSelect: onOpenSqlHelper,
                  },
              ] satisfies SceneAction[])
            : []),
        ...(showStatusAction
            ? ([
                  {
                      group: 'edit',
                      section: 'status',
                      id: isComplete ? `${RESOURCE_TYPE}-menubar-resume` : `${RESOURCE_TYPE}-menubar-stop`,
                      label: isComplete ? 'Resume survey' : 'Stop survey',
                      icon: isComplete ? <IconPlay /> : <IconPause />,
                      opensFloatingUi: true,
                      disabledReason: editorDisabledReason,
                      onSelect: () =>
                          isComplete
                              ? openResumeSurveyDialog(survey, () => resumeSurvey())
                              : openStopSurveyDialog(() => stopSurvey()),
                      pinned: { order: 3, variant: 'secondary', render: () => <QuillSurveyStatusAction /> },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(todayRailNav
            ? ([
                  {
                      group: 'view',
                      id: `${RESOURCE_TYPE}-menubar-details`,
                      label: 'Survey details',
                      icon: <IconInfo />,
                      opensFloatingUi: true,
                      onSelect: onOpenDetails,
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-feedback`,
            label: 'Feedback',
            icon: <IconMessage />,
            opensFloatingUi: true,
            tooltip: 'Have any questions or feedback?',
            // The feedback survey opens on a click of the title button, so the row forwards its click there.
            onSelect: () => document.getElementById(FEEDBACK_BUTTON_ID)?.click(),
            pinned: { order: 1, variant: 'icon', render: () => <SurveyFeedbackButton /> },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
