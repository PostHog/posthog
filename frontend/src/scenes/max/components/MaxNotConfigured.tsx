import { IconLock } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

/**
 * Shown when PostHog AI (Max) is rendered on a self-hosted instance without the LLM provider keys it needs.
 * Everything runs on Anthropic. Only the legacy chat also needs OpenAI, for its conversation title, so
 * task surfaces pass `needsOpenAiKey={false}` and ask for ANTHROPIC_API_KEY alone.
 */
export function MaxNotConfigured({ needsOpenAiKey = true }: { needsOpenAiKey?: boolean }): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center text-center grow gap-4 px-4 py-8 max-w-prose mx-auto">
            <div className="flex p-2 select-none opacity-60">
                <Logomark size="md" />
            </div>
            <div>
                <h2 className="text-xl font-bold mb-2 flex items-center justify-center gap-2">
                    <IconLock />
                    PostHog AI isn't set up yet
                </h2>
                <p className="text-sm text-tertiary text-pretty mb-0">
                    PostHog AI runs on your own LLM provider keys. Set <code>ANTHROPIC_API_KEY</code>
                    {needsOpenAiKey && (
                        <>
                            {' '}
                            and <code>OPENAI_API_KEY</code>
                        </>
                    )}{' '}
                    for this instance and restart PostHog to start chatting.
                </p>
            </div>
            <CodeSnippet language={Language.Bash} className="w-full text-left">
                {needsOpenAiKey
                    ? 'ANTHROPIC_API_KEY=sk-ant-...\nOPENAI_API_KEY=sk-...'
                    : 'ANTHROPIC_API_KEY=sk-ant-...'}
            </CodeSnippet>
            <p className="text-sm text-tertiary text-pretty mb-0">
                On a hobby deploy, add the keys to your <code>.env</code> file and run <code>./bin/upgrade-hobby</code>,
                or set them during install.{' '}
                <Link
                    to="https://posthog.com/docs/self-host/configure/environment-variables?utm_medium=in-product&utm_campaign=max-not-configured"
                    target="_blank"
                    targetBlankIcon
                    data-attr="max-not-configured-configure-key"
                >
                    Configuring environment variables
                </Link>
            </p>
        </div>
    )
}
