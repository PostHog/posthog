import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'
import { SurveysFinalSteps } from './SurveysFinalSteps'

export function NextJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNextJSInstructions />
            <SurveysFinalSteps />
        </>
    )
}
