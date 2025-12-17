import { useValues } from 'kea'

import { Language } from 'lib/components/CodeSnippet'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function MCPInstallBanner({ variant }: { variant?: 'top' | 'sdk' }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    const flagValue = featureFlags[FEATURE_FLAGS.ONBOARDING_MCP_OPTION]

    if (!flagValue || flagValue === 'control') {
        return null
    }

    if (variant === 'top' && flagValue !== 'banner-top') {
        return null
    }

    if (variant === 'sdk' && flagValue !== 'banner-per-sdk') {
        return null
    }

    return (
        <>
            <h2>Automated Installation</h2>
            <LemonBanner type="info" hideIcon={true}>
                <div className="flex flex-col p-2">
                    <p className="font-normal pb-1">
                        Install our MCP server, then ask your AI assistant to set up PostHog for you.
                    </p>
                    <p className="font-normal pb-2">Run this command:</p>
                    <CodeSnippet language={Language.Bash}>npx @posthog/wizard mcp add</CodeSnippet>
                    <p className="font-normal pt-2 pb-2">Then prompt your AI assistant:</p>
                    <CodeSnippet language={Language.Text}>Help me set up PostHog</CodeSnippet>
                    <Link
                        to="https://posthog.com/docs/model-context-protocol"
                        className="pt-2"
                        onClick={() => {
                            if (typeof posthog !== 'undefined') {
                                posthog.capture('onboarding_mcp_docs_clicked')
                            }
                        }}
                        target="_blank"
                        targetBlankIcon
                        disableDocsPanel
                    >
                        Learn more about our MCP server
                    </Link>
                </div>
            </LemonBanner>
            <div className="text-center text-sm text-muted mt-4 mb-2">OR</div>
        </>
    )
}
