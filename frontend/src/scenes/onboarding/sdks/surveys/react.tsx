import { SDKInstallReactInstructions } from '../sdk-install-instructions/react'
import { SurveysFinalSteps } from './SurveysFinalSteps'

export function ReactInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallReactInstructions />
            <SurveysFinalSteps />
        </>
    )
}
