import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { VerifySourceMaps } from '../VerifySourceMaps'

export function NextJSSourceMapsInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const host = apiHostOrigin()

    return (
        <>
            <h3>Install the PostHog Next.js config package</h3>
            <p>
                This package handles automatic source map generation and upload for error tracking. Install it using
                your package manager:
            </p>
            <CodeSnippet language={Language.Bash}>
                {[
                    'npm install @posthog/nextjs-config',
                    '# OR',
                    'yarn add @posthog/nextjs-config',
                    '# OR',
                    'pnpm add @posthog/nextjs-config',
                ].join('\n')}
            </CodeSnippet>

            <h3>Add PostHog config to your Next.js app</h3>
            <p>
                Add the following to your <code>next.config.js</code> file:
            </p>
            <CodeSnippet language={Language.JavaScript}>
                {nextConfig(currentTeam?.id?.toString() ?? '<team_id>', host)}
            </CodeSnippet>

            <h3>Build your project for production</h3>
            <p>
                Build your project for production. The Next.js config package will automatically generate and upload
                source maps to PostHog during the build process.
            </p>

            <VerifySourceMaps />
        </>
    )
}

const nextConfig = (
    teamId: string,
    host: string
): string => `import { withPostHogConfig } from "@posthog/nextjs-config";

const nextConfig = {
  //...your nextjs config,
};

export default withPostHogConfig(nextConfig, {
  personalApiKey: '<ph_personal_api_key>', // Your personal API key from PostHog settings
  envId: '${teamId}', // Your environment ID (project ID)
  host: '${host}', // Optional: Your PostHog instance URL, defaults to https://us.posthog.com
  sourcemaps: { // Optional
    enabled: true, // Optional: Enable sourcemaps generation and upload, defaults to true on production builds
    project: "my-application", // Optional: Project name, defaults to git repository name
    version: "1.0.0", // Optional: Release version, defaults to current git commit
    deleteAfterUpload: true, // Optional: Delete sourcemaps after upload, defaults to true
  },
});`
