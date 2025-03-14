import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallAngularInstructions } from '../sdk-install-instructions'
import { JSManualCapture } from './FinalSteps'

export function AngularInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallAngularInstructions />
            <Autocapture />
            <JSManualCapture />
        </>
    )
}

const Autocapture = (): JSX.Element => {
    return (
        <>
            <h3>Capturing exceptions</h3>
            <p>You will need to override Angular's default ErrorHandler provider:</p>
            <CodeSnippet language={Language.JavaScript}>SCRIPT GOES HERE</CodeSnippet>
        </>
    )
}
