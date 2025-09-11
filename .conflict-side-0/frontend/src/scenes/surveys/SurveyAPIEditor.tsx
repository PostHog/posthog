import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { Survey } from '~/types'

import { NewSurvey } from './constants'

export function SurveyAPIEditor({ survey }: { survey: Survey | NewSurvey }): JSX.Element {
    // Make sure this is synced to SurveyAPISerializer
    const apiSurvey = {
        id: survey.id,
        name: survey.name,
        description: survey.description,
        type: 'api',
        linked_flag_key: survey.linked_flag ? survey.linked_flag.key : null,
        targeting_flag_key: survey.targeting_flag ? survey.targeting_flag.key : null,
        questions: survey.questions,
        conditions: survey.conditions,
        start_date: survey.start_date,
        end_date: survey.end_date,
    }

    return (
        <CodeSnippet wrap language={Language.JSON} compact>
            {JSON.stringify(apiSurvey, null, 2)}
        </CodeSnippet>
    )
}
