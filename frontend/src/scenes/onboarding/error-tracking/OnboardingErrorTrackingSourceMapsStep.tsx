import { LemonCollapse } from '@posthog/lemon-ui'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useState } from 'react'

import { OnboardingStep } from '../OnboardingStep'
import { OnboardingStepKey } from '~/types'

export function OnboardingErrorTrackingSourceMapsStep({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element {
    const [activeKey, setActiveKey] = useState<'cli' | 'no-minification' | 'public-source-maps' | undefined>(undefined)

    return (
        <OnboardingStep
            title="Link source maps"
            stepKey={stepKey}
            continueOverride={activeKey !== 'cli' ? <></> : undefined}
            showSkip={activeKey !== 'cli'}
        >
            <p>
                Some languages, bundlers and frameworks obfuscate code making debugging difficult. Source maps are
                essential to transform code back to the original source. Choose the option that matches your setup to
                ensure stack traces are readable.
            </p>
            <LemonCollapse
                activeKey={activeKey}
                onChange={(v) => setActiveKey(v ?? undefined)}
                panels={[
                    {
                        key: 'no-minification',
                        header: 'Unminified code',
                        content: (
                            <p>
                                Not all languages and frameworks are minified. For example Python and Node code often
                                remains readable and there is no need to upload source maps.
                            </p>
                        ),
                    },
                    {
                        key: 'public-source-maps',
                        header: 'Public source maps',
                        content: (
                            <p>
                                If source maps are publicly available PostHog can fetch and provide readable stack
                                traces without any additional setup.
                            </p>
                        ),
                    },
                    {
                        key: 'cli',
                        header: 'Upload source maps',
                        content: (
                            <>
                                <p>
                                    Should you wish to keep your source maps private you will need to upload source maps
                                    during your build process to see unminified code in your stack traces.
                                </p>
                                <p>
                                    The <code>posthog-cli</code> handles this process. You will need to install it via
                                    Cargo and complete the necessary authentication.
                                </p>
                                <CodeSnippet language={Language.Bash}>
                                    {[
                                        "curl --proto '=https' --tlsv1.2 -LsSf https://github.com/PostHog/posthog/releases/download/posthog-cli-v0.0.2/posthog-cli-installer.sh | sh",
                                        'posthog-cli-update',
                                    ].join('\n')}
                                </CodeSnippet>
                                <p>
                                    Once you've built your application and have bundled assets that serve your site,
                                    inject the context required by PostHog to associate the maps with the served code.
                                    You will then need to upload the modified assets to PostHog. Both of these
                                    operations can be done by running the respective sourcemap commands.
                                </p>
                                <CodeSnippet language={Language.Bash}>
                                    {[
                                        'posthog-cli sourcemap inject --directory ./path/to/assets',
                                        'posthog-cli sourcemap upload --directory ./path/to/assets',
                                    ].join('\n')}
                                </CodeSnippet>
                            </>
                        ),
                    },
                ]}
            />
        </OnboardingStep>
    )
}
