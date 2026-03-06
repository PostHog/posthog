import { LemonBanner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SourceMapsAPIKeyBanner } from '../SourceMapsAPIKeyBanner'

export function IOSSourceMapsInstructions(): JSX.Element {
    return (
        <>
            <SourceMapsAPIKeyBanner />

            <h3>Install the PostHog CLI</h3>
            <p>The PostHog CLI handles dSYM upload for iOS apps. Install it using one of these methods:</p>
            <h4 className="text-sm font-semibold mt-4 mb-2">npm:</h4>
            <CodeSnippet language={Language.Bash}>npm install -g @posthog/cli</CodeSnippet>
            <h4 className="text-sm font-semibold mt-4 mb-2">curl:</h4>
            <CodeSnippet language={Language.Bash}>
                {[
                    "curl --proto '=https' --tlsv1.2 -LsSf https://github.com/PostHog/posthog/releases/latest/download/posthog-cli-installer.sh | sh",
                    'posthog-cli-update',
                ].join('\n')}
            </CodeSnippet>

            <h3>Authenticate the CLI</h3>
            <p>
                Run the following command to authenticate with PostHog. This opens your browser where you select your
                organization, project, and API scopes to grant:
            </p>
            <CodeSnippet language={Language.Bash}>posthog-cli login</CodeSnippet>

            <h3>CI/CD configuration</h3>
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
                                <strong>Personal API key</strong> with <code>error tracking write</code> and{' '}
                                <code>organization read</code> scopes
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <h3>Configure Xcode build settings</h3>
            <p>In Xcode, configure your build settings to generate dSYMs:</p>
            <ol className="list-decimal list-inside space-y-1 my-2 ml-2">
                <li>Open your project in Xcode</li>
                <li>Select your target</li>
                <li>Go to Build Settings</li>
                <li>Search for "Debug Information Format"</li>
                <li>
                    Make sure Release configurations have <code>DWARF with dSYM File</code>
                </li>
            </ol>

            <LemonBanner type="warning" className="my-4">
                <strong>Disable User Script Sandboxing</strong>
                <p className="mt-1">
                    You must disable User Script Sandboxing for the upload script to work. In Build Settings, search for
                    "User Script Sandboxing" and set <code>ENABLE_USER_SCRIPT_SANDBOXING</code> to <strong>No</strong>.
                </p>
                <p className="mt-2 text-sm">
                    <strong>Why?</strong> Xcode restricts build phase scripts from accessing files outside the build
                    directory. The dSYM upload script needs to traverse dSYM bundles, run external tools, and access the
                    network. This is the same requirement as other crash reporting tools.
                </p>
            </LemonBanner>

            <h3>Add build phase script</h3>
            <p>Add a Run Script build phase to automatically upload dSYMs after each build:</p>
            <ol className="list-decimal list-inside space-y-1 my-2 ml-2">
                <li>In Xcode, select your target</li>
                <li>Go to Build Phases</li>
                <li>Click the + button and select "New Run Script Phase"</li>
                <li>Drag it to run after the "Compile Sources" phase</li>
                <li>Rname to "PostHog - Upload Symbols" or similar</li>
                <li>Add the appropriate script for your package manager:</li>
            </ol>

            <h4 className="text-sm font-semibold mt-4 mb-2">Swift Package Manager (SPM):</h4>
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
                <strong>Note:</strong> <code>POSTHOG_INCLUDE_SOURCE=1</code> includes source code snippets in the dSYM
                upload. This increases upload size and time, so only enable it if you need source code context in the
                PostHog UI.
            </p>

            <h3>Build and verify</h3>
            <p>
                Build your app in Xcode. The dSYM upload script will automatically run and upload symbols to PostHog.
                Check the build log output for confirmation.
            </p>
        </>
    )
}
