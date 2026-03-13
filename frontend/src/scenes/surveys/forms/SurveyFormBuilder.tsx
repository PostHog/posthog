import { BindLogic } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { surveyLogic } from '../surveyLogic'
import { SurveyFormBuilderLogicProps, surveyFormBuilderLogic } from './surveyFormBuilderLogic'

export const scene: SceneExport<SurveyFormBuilderLogicProps> = {
    component: SurveyFormBuilderComponent,
    paramsToProps: ({ params: { id } }): SurveyFormBuilderLogicProps => ({ id: id || 'new' }),
}

function SurveyFormBuilderComponent({ id }: SurveyFormBuilderLogicProps): JSX.Element {
    return (
        <BindLogic logic={surveyFormBuilderLogic} props={{ id }}>
            <BindLogic logic={surveyLogic} props={{ id }}>
                <SurveyFormBuilder id={id} />
            </BindLogic>
        </BindLogic>
    )
}

function SurveyFormBuilder({ id }: SurveyFormBuilderLogicProps): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name={`Form ${id}`}
                resourceType={{
                    type: 'survey',
                }}
            />
            <div className="flex flex-col h-full">
                <p>The survey is: {id}</p>
            </div>
        </SceneContent>
    )
}
