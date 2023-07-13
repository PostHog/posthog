import { Survey } from '~/types'
import { NewSurvey } from './surveyLogic'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

export function SurveyAPIEditor({ survey }: { survey: Survey | NewSurvey }): JSX.Element {
    // Make sure this is synced to SurveyAPISerializer
    const {
        appearance,
        archived,
        linked_flag,
        targeting_flag,
        targeting_flag_filters,
        created_at,
        created_by,
        linked_flag_id,
        ...apiSurvey
    } = survey
    const apiSurveyWithFlagKeys = {
        ...apiSurvey,
        ...(linked_flag ? { linked_flag: linked_flag.key } : {}),
        ...(targeting_flag ? { targeting_flag: targeting_flag.key } : {}),
    }
    return (
        <div className="flex flex-col">
            <h4 className="text-center">API survey response</h4>
            <CodeSnippet wrap language={Language.JSON}>
                {JSON.stringify(apiSurveyWithFlagKeys, null, 2)}
            </CodeSnippet>
        </div>
    )
}
