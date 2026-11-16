import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArchive, IconCode, IconCopy, IconDownload, IconInfo, IconSend, IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import {
    SURVEY_FOLLOW_UP_WORKFLOW_LABEL,
    startSurveyFollowUpWorkflow,
} from 'scenes/surveys/components/SurveyFollowUpWorkflowButton'
import { canDeleteSurvey, openArchiveSurveyDialog, openDeleteSurveyDialog } from 'scenes/surveys/surveyDialogs'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { isSurveyDraft, surveysLogic } from 'scenes/surveys/surveysLogic'
import { useSurveyResponsesExport } from 'scenes/surveys/SurveyViewRedesign/SurveySidebar'
import { urls } from 'scenes/urls'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from '~/layout/scenes/components/SceneMenuBar'
import { AccessControlLevel, AccessControlResourceType, ExporterFormat, Survey } from '~/types'

import { messageAudienceAccessDisabledReason } from 'products/workflows/frontend/MessageAudience/messageAudience'

import { NEW_SURVEY } from './constants'

const RESOURCE_TYPE = 'survey'

type SurveySceneMenuBarProps = {
    onOpenSqlHelper: () => void
    onOpenDetails: () => void
}

export function SurveySceneMenuBar(props: SurveySceneMenuBarProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <SurveySceneMenuBarInner {...props} />
}

function SurveySceneMenuBarInner({ onOpenSqlHelper, onOpenDetails }: SurveySceneMenuBarProps): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { archiveSurvey } = useActions(surveyLogic)
    const { deleteSurvey, duplicateSurvey, setSurveyToDuplicate } = useActions(surveysLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { push } = useActions(router)
    const { disabledReason: exportDisabledReason, exportResponses } = useSurveyResponsesExport()
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const savedSurveyId = survey.id !== NEW_SURVEY.id ? survey.id : null
    const hasMultipleProjects = !!(currentOrganization?.teams && currentOrganization.teams.length > 1)
    const isDraft = isSurveyDraft(survey)
    const followUpDisabledReason = messageAudienceAccessDisabledReason()

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                {savedSurveyId && (
                    <>
                        <SceneMenuBarSubMenu label="Create">
                            <SceneMenuBarItem
                                disabled={!!followUpDisabledReason}
                                tooltip={followUpDisabledReason ?? undefined}
                                onClick={() => startSurveyFollowUpWorkflow(savedSurveyId)}
                                data-attr={`${RESOURCE_TYPE}-menubar-follow-up-workflow`}
                            >
                                <IconSend />
                                {SURVEY_FOLLOW_UP_WORKFLOW_LABEL}
                            </SceneMenuBarItem>
                        </SceneMenuBarSubMenu>
                        <SceneMenuBarSeparator />
                    </>
                )}
                <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                {canCopyToProject && savedSurveyId && (
                    <SceneMenuBarItem
                        onClick={() => push(urls.resourceTransfer('Survey', savedSurveyId))}
                        data-attr={`${RESOURCE_TYPE}-menubar-copy-to-project`}
                    >
                        <IconCopy />
                        Copy to another project
                    </SceneMenuBarItem>
                )}
                {!isDraft && (
                    <>
                        <SceneMenuBarItem
                            disabled={!!exportDisabledReason}
                            tooltip={exportDisabledReason ?? undefined}
                            onClick={() => exportResponses(ExporterFormat.CSV)}
                            data-attr={`${RESOURCE_TYPE}-menubar-export-csv`}
                        >
                            <IconDownload />
                            Export responses as CSV
                        </SceneMenuBarItem>
                        <SceneMenuBarItem
                            disabled={!!exportDisabledReason}
                            tooltip={exportDisabledReason ?? undefined}
                            onClick={() => exportResponses(ExporterFormat.XLSX)}
                            data-attr={`${RESOURCE_TYPE}-menubar-export-xlsx`}
                        >
                            <IconDownload />
                            Export responses as Excel
                        </SceneMenuBarItem>
                    </>
                )}
                {(!survey.archived || canDeleteSurvey(survey)) && <SceneMenuBarSeparator />}
                {!survey.archived && (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Survey}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={survey.user_access_level}
                    >
                        {({ disabledReason }) => (
                            <SceneMenuBarItem
                                variant="destructive"
                                disabled={!!disabledReason}
                                onClick={() => openArchiveSurveyDialog(survey, archiveSurvey)}
                                data-attr={`${RESOURCE_TYPE}-menubar-archive`}
                            >
                                <IconArchive />
                                Archive
                            </SceneMenuBarItem>
                        )}
                    </AccessControlAction>
                )}
                {canDeleteSurvey(survey) && (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Survey}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={survey.user_access_level}
                    >
                        {({ disabledReason }) => (
                            <SceneMenuBarItem
                                variant="destructive"
                                disabled={!!disabledReason}
                                onClick={() => openDeleteSurveyDialog(survey, () => deleteSurvey(survey.id))}
                                data-attr={`${RESOURCE_TYPE}-menubar-delete`}
                            >
                                <IconTrash />
                                Delete permanently
                            </SceneMenuBarItem>
                        )}
                    </AccessControlAction>
                )}
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="Edit" dataAttr={`${RESOURCE_TYPE}-menubar-edit`}>
                <SceneMenuBarItem
                    onClick={() => {
                        const existingSurvey = survey as Survey
                        if (hasMultipleProjects) {
                            setSurveyToDuplicate(existingSurvey)
                        } else {
                            duplicateSurvey(existingSurvey)
                        }
                    }}
                    data-attr={`${RESOURCE_TYPE}-menubar-duplicate`}
                >
                    <IconCopy />
                    Duplicate
                </SceneMenuBarItem>
                {!isDraft && (
                    <SceneMenuBarItem
                        opensFloatingUi
                        onClick={onOpenSqlHelper}
                        data-attr={`${RESOURCE_TYPE}-menubar-sql-query`}
                    >
                        <IconCode />
                        SQL query
                    </SceneMenuBarItem>
                )}
            </SceneMenuBarMenu>
            {todayRailNav && (
                <SceneMenuBarMenu label="View" dataAttr={`${RESOURCE_TYPE}-menubar-view`}>
                    <SceneMenuBarItem
                        opensFloatingUi
                        onClick={onOpenDetails}
                        data-attr={`${RESOURCE_TYPE}-menubar-details`}
                    >
                        <IconInfo />
                        Survey details
                    </SceneMenuBarItem>
                </SceneMenuBarMenu>
            )}
        </SceneMenuBar>
    )
}
