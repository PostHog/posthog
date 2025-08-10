import { SDKInstallFlutterInstructions } from '../sdk-install-instructions'

export function FlutterInstructions(): JSX.Element {
    return <SDKInstallFlutterInstructions includeSurveys={true} requiresManualInstall={true} />
}
