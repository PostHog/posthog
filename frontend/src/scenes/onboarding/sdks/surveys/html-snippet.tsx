import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { SDKHtmlSnippetInstructions } from '../sdk-install-instructions/html-snippet'
import { SurveysFinalSteps } from './SurveysFinalSteps'

export function HTMLSnippetInstructions(): JSX.Element {
    return (
        <>
            <SDKHtmlSnippetInstructions />
            <LemonDivider thick dashed className="my-4" />
            <SurveysFinalSteps />
        </>
    )
}
