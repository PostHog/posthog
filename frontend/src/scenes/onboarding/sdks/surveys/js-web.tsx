import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { SDKInstallJSWebInstructions } from '../sdk-install-instructions'
import { SurveysFinalSteps } from './SurveysFinalSteps'

export function JSWebInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallJSWebInstructions />
            <LemonDivider thick dashed className="my-4" />
            <SurveysFinalSteps />
        </>
    )
}
