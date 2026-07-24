import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArchive, IconCopy, IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { canDeleteSurvey, openArchiveSurveyDialog, openDeleteSurveyDialog } from 'scenes/surveys/surveyDialogs'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { urls } from 'scenes/urls'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'
import { AccessControlLevel, AccessControlResourceType, Survey } from '~/types'

const RESOURCE_TYPE = 'survey'

export function SurveySceneMenuBar({ id }: { id: string }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <SurveySceneMenuBarInner id={id} />
}

function SurveySceneMenuBarInner({ id }: { id: string }): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const { archiveSurvey } = useActions(surveyLogic)
    const { deleteSurvey, duplicateSurvey, setSurveyToDuplicate } = useActions(surveysLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { push } = useActions(router)

    if (!survey || !survey.id) {
        return null
    }

    const surveyId = survey.id as string
    const hasMultipleProjects = !!(currentOrganization?.teams && currentOrganization.teams.length > 1)
    const canDelete = canDeleteSurvey(survey)
    const canArchive = !survey.archived

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                <SceneMenuBarFileItems dataAttrKey={RESOURCE_TYPE} />
                {canCopyToProject && (
                    <SceneMenuBarItem
                        onClick={() => push(urls.resourceTransfer('Survey', surveyId))}
                        data-attr={`${RESOURCE_TYPE}-menubar-copy-to-project`}
                    >
                        <IconCopy />
                        Copy to another project
                    </SceneMenuBarItem>
                )}
                {(canArchive || canDelete) && <SceneMenuBarSeparator />}
                {canArchive && (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Survey}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={survey.user_access_level}
                    >
                        {({ disabledReason }) => (
                            <SceneMenuBarItem
                                variant="destructive"
                                disabled={!!disabledReason}
                                opensFloatingUi
                                onClick={() => openArchiveSurveyDialog(survey as Survey, archiveSurvey)}
                                data-attr={`${RESOURCE_TYPE}-menubar-archive`}
                            >
                                <IconArchive />
                                Archive
                            </SceneMenuBarItem>
                        )}
                    </AccessControlAction>
                )}
                {canDelete && (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Survey}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={survey.user_access_level}
                    >
                        {({ disabledReason }) => (
                            <SceneMenuBarItem
                                variant="destructive"
                                disabled={!!disabledReason}
                                opensFloatingUi
                                onClick={() => openDeleteSurveyDialog(survey as Survey, () => deleteSurvey(id))}
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
                        const existing = survey as Survey
                        if (hasMultipleProjects) {
                            setSurveyToDuplicate(existing)
                        } else {
                            duplicateSurvey(existing)
                        }
                    }}
                    data-attr={`${RESOURCE_TYPE}-menubar-duplicate`}
                >
                    <IconCopy />
                    Duplicate
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
