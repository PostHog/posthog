import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { Survey } from '~/types'

import { buildApiSurveySnippet } from './apiSurveySnippet'
import { NewSurvey } from './constants'

export function SurveyAPIEditor({ survey }: { survey: Survey | NewSurvey }): JSX.Element {
    return (
        <CodeSnippet wrap language={Language.JavaScript} compact>
            {buildApiSurveySnippet(survey)}
        </CodeSnippet>
    )
}
