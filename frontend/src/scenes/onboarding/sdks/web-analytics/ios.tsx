import { SDKInstallIOSInstructions } from '../sdk-install-instructions'

export function iOSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallIOSInstructions includeReplay={true} />
        </>
    )
}
