import { LemonBanner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SourceMapsAPIKeyBanner } from '../SourceMapsAPIKeyBanner'

export function IOSSourceMapsInstructions(): JSX.Element {
    return (
        <>
            <SourceMapsAPIKeyBanner />

            <h3>1. Install and authenticate the PostHog CLI</h3>
            <p>
                The PostHog CLI handles dSYM upload for iOS apps. iOS dSYM support requires{' '}
                <strong>CLI version 0.7.0 or later</strong>. Install it using one of these methods:
            </p>
            <h4 className="text-sm font-semibold mt-4 mb-2">npm:</h4>
            <CodeSnippet language={Language.Bash}>npm install -g @posthog/cli</CodeSnippet>
            <h4 className="text-sm font-semibold mt-4 mb-2">curl:</h4>
            <CodeSnippet language={Language.Bash}>
                {[
                    "curl --proto '=https' --tlsv1.2 -LsSf https://github.com/PostHog/posthog/releases/latest/download/posthog-cli-installer.sh | sh",
                    'posthog-cli-update',
                ].join('\n')}
            </CodeSnippet>

            <p className="mt-4">
                Run the following command to authenticate with PostHog. This opens your browser where you select your
                organization, project, and API scopes to grant:
            </p>
            <CodeSnippet language={Language.Bash}>posthog-cli login</CodeSnippet>

            <h4 className="text-sm font-semibold mt-4 mb-2">CI/CD configuration:</h4>
            <p>
                If you are using the CLI in a CI/CD environment such as GitHub Actions, you can set environment
                variables to authenticate:
            </p>
            <div className="overflow-x-auto my-4">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="border-b">
                            <th className="text-left py-2 px-2">Environment Variable</th>
                            <th className="text-left py-2 px-2">Description</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr className="border-b">
                            <td className="py-2 px-2">
                                <code>POSTHOG_CLI_HOST</code>
                            </td>
                            <td className="py-2 px-2">
                                The PostHog host to connect to (default: https://us.posthog.com)
                            </td>
                        </tr>
                        <tr className="border-b">
                            <td className="py-2 px-2">
                                <code>POSTHOG_CLI_PROJECT_ID</code>
                            </td>
                            <td className="py-2 px-2">PostHog project ID</td>
                        </tr>
                        <tr className="border-b">
                            <td className="py-2 px-2">
                                <code>POSTHOG_CLI_API_KEY</code>
                            </td>
                            <td className="py-2 px-2">
                                <strong>Personal API key</strong> with <code>error_tracking:write</code> and{' '}
                                <code>organization:read</code> scopes
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <h3>2. Configure build settings</h3>
            <p>In Xcode, configure your build settings to generate dSYMs:</p>
            <ol className="list-decimal list-inside space-y-1 my-2 ml-2">
                <li>Open your project in Xcode</li>
                <li>Select your target</li>
                <li>
                    Go to <strong>Build Settings</strong>
                </li>
                <li>
                    Search for <strong>Debug Information Format</strong>
                </li>
                <li>
                    Make sure Release configurations have <code>DWARF with dSYM File</code>
                </li>
            </ol>

            <LemonBanner type="warning" className="my-4">
                <strong>Disable User Script Sandboxing</strong>
                <p className="mt-1">You must disable User Script Sandboxing for the upload script to work:</p>
                <ol className="list-decimal list-inside space-y-1 my-2 ml-4">
                    <li>
                        In Build Settings, search for <strong>User Script Sandboxing</strong> (
                        <code>ENABLE_USER_SCRIPT_SANDBOXING</code>)
                    </li>
                    <li>
                        Set <code>ENABLE_USER_SCRIPT_SANDBOXING</code> to <strong>No</strong>
                    </li>
                </ol>
                <p className="mt-2 text-sm">
                    <strong>Why is this required?</strong> When User Script Sandboxing is enabled, Xcode only allows run
                    scripts to access files explicitly specified in the build phase's <strong>Input Files</strong>. The
                    dSYM upload script needs to walk directories to locate and read dSYM bundles, and execute{' '}
                    <code>posthog-cli</code> which are currently not allowed with User Script Sandboxing enabled.
                </p>
            </LemonBanner>

            <h3>3. Add build phase script</h3>
            <p>
                To symbolicate crash reports, PostHog needs your project's debug symbol (dSYM) files. The following
                script automatically processes and uploads dSYMs whenever you build your app.
            </p>
            <p className="mt-2">
                Add a <strong>Run Script</strong> build phase:
            </p>
            <ol className="list-decimal list-inside space-y-1 my-2 ml-2">
                <li>In Xcode, select your main app target</li>
                <li>
                    Go to <strong>Build Phases</strong> tab
                </li>
                <li>
                    Click the <strong>+</strong> button and select <strong>New Run Script Phase</strong>
                </li>
                <li>Make sure it's set to run last (after "Copy Bundle Resources" or similar)</li>
                <li>Add the appropriate script for your package manager:</li>
            </ol>

            <h4 className="text-sm font-semibold mt-4 mb-2">Swift Package Manager:</h4>
            <CodeSnippet language={Language.Bash}>
                {'${BUILD_DIR%/Build/*}/SourcePackages/checkouts/posthog-ios/build-tools/upload-symbols.sh'}
            </CodeSnippet>

            <h4 className="text-sm font-semibold mt-4 mb-2">CocoaPods:</h4>
            <CodeSnippet language={Language.Bash}>{'${PODS_ROOT}/PostHog/build-tools/upload-symbols.sh'}</CodeSnippet>

            <h3>4. Optional: Include source code context</h3>
            <p>
                By default, only debug symbols are uploaded. To include source code snippets in your stack traces (for
                better debugging context), set the <code>POSTHOG_INCLUDE_SOURCE</code> environment variable:
            </p>
            <ol className="list-decimal list-inside space-y-1 my-2 ml-2">
                <li>In the Run Script build phase, click the chevron to expand</li>
                <li>Set the environment variable when calling the upload script:</li>
            </ol>

            <h4 className="text-sm font-semibold mt-4 mb-2">Swift Package Manager:</h4>
            <CodeSnippet language={Language.Bash}>
                {
                    'POSTHOG_INCLUDE_SOURCE=1 ${BUILD_DIR%/Build/*}/SourcePackages/checkouts/posthog-ios/build-tools/upload-symbols.sh'
                }
            </CodeSnippet>

            <h4 className="text-sm font-semibold mt-4 mb-2">CocoaPods:</h4>
            <CodeSnippet language={Language.Bash}>
                {'POSTHOG_INCLUDE_SOURCE=1 ${PODS_ROOT}/PostHog/build-tools/upload-symbols.sh'}
            </CodeSnippet>

            <p className="text-sm text-muted mt-2">
                <strong>Note:</strong> Enabling this flag uploads your source code to PostHog's servers. This is
                disabled by default. Only enable it if your organization's security and data-governance policies permit
                source code to leave your build environment. It also increases upload size and build times.
            </p>

            <h3>5. Build and verify</h3>
            <p>
                Build your app in Xcode. The dSYM upload script will automatically run and upload symbols to PostHog.
                Check the build log output for confirmation.
            </p>
        </>
    )
}
