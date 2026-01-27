import { BindLogic, useActions, useValues } from 'kea'

import { IconArchive, IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { organizationLogic } from 'scenes/organizationLogic'
import { canDeleteSurvey, openArchiveSurveyDialog, openDeleteSurveyDialog } from 'scenes/surveys/surveyDialogs'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'

import { sidePanelContextLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelContextLogic'
import { ScenePanelActionsSection, ScenePanelDivider, ScenePanelInfoSection } from '~/layout/scenes/SceneLayout'
import { AccessControlLevel, AccessControlResourceType, Survey } from '~/types'

const RESOURCE_TYPE = 'survey'

export function SurveyPanelDetails(): JSX.Element | null {
    const { sceneSidePanelContext } = useValues(sidePanelContextLogic)
    const surveyId = sceneSidePanelContext?.activity_item_id

    if (!surveyId) {
        return null
    }

    return (
        <BindLogic logic={surveyLogic} props={{ id: surveyId }}>
            <SurveyPanelDetailsContent />
        </BindLogic>
    )
}

function SurveyPanelDetailsContent(): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const { archiveSurvey } = useActions(surveyLogic)
    const { deleteSurvey, duplicateSurvey, setSurveyToDuplicate } = useActions(surveysLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const hasMultipleProjects = currentOrganization?.teams && currentOrganization.teams.length > 1

    if (!survey?.id || survey.id === 'new') {
        return null
    }

    return (
        <>
            <ScenePanelInfoSection>
                <SceneFile dataAttrKey={RESOURCE_TYPE} />
            </ScenePanelInfoSection>
            <ScenePanelDivider />
            <ScenePanelActionsSection>
                <SceneDuplicate
                    dataAttrKey={RESOURCE_TYPE}
                    onClick={() => {
                        const existingSurvey = survey as Survey
                        if (hasMultipleProjects) {
                            setSurveyToDuplicate(existingSurvey)
                        } else {
                            duplicateSurvey(existingSurvey)
                        }
                    }}
                />
            </ScenePanelActionsSection>
            <ScenePanelDivider />
            {!survey.archived && (
                <ScenePanelActionsSection>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Survey}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={survey.user_access_level}
                    >
                        <ButtonPrimitive
                            menuItem
                            data-attr={`${RESOURCE_TYPE}-archive`}
                            onClick={() => openArchiveSurveyDialog(survey, archiveSurvey)}
                        >
                            <IconArchive />
                            Archive
                        </ButtonPrimitive>
                    </AccessControlAction>
                </ScenePanelActionsSection>
            )}
            {canDeleteSurvey(survey) && (
                <ScenePanelActionsSection>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Survey}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={survey.user_access_level}
                    >
                        <ButtonPrimitive
                            menuItem
                            variant="danger"
                            data-attr={`${RESOURCE_TYPE}-delete`}
                            onClick={() => openDeleteSurveyDialog(survey, () => deleteSurvey(survey.id))}
                        >
                            <IconTrash />
                            Delete permanently
                        </ButtonPrimitive>
                    </AccessControlAction>
                </ScenePanelActionsSection>
            )}
        </>
    )
}
