import { Survey } from '~/types'
import { NewSurvey } from './surveyLogic'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

export function SurveyAPIEditor({ survey }: { survey: Survey | NewSurvey }): JSX.Element {
    const { appearance, ...apiSurvey } = survey
    return (
        <div className="flex flex-col">
            <h4 className="text-center">API survey response</h4>
            <CodeSnippet wrap language={Language.JSON}>
                {JSON.stringify(apiSurvey, null, 2)}
            </CodeSnippet>
        </div>
    )
}
