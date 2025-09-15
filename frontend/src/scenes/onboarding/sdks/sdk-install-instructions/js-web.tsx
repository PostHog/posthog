import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function JSInstallSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.Bash}>
            {['npm install posthog-js', '# OR', 'yarn add posthog-js', '# OR', 'pnpm add posthog-js'].join('\n')}
        </CodeSnippet>
    )
}

export function JSSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]

    return (
        <CodeSnippet language={Language.JavaScript}>
            {[
                "import posthog from 'posthog-js'",
                '',
                `posthog.init('${currentTeam?.api_token}',`,
                `    {`,
                `        api_host: '${apiHostOrigin()}',`,
                isPersonProfilesDisabled
                    ? ``
                    : `        person_profiles: 'identified_only' // or 'always' to create profiles for anonymous users as well`,
                `    }`,
                `)`,
            ].join('\n')}
        </CodeSnippet>
    )
}

export function SDKInstallJSWebInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <JSInstallSnippet />
            <h3>Initialize</h3>
            <JSSetupSnippet />
        </>
    )
}
