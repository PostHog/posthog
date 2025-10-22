import { useActions, useValues } from 'kea'

import { LemonCard } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../OnboardingStep'
import { SourceMapsInstructionsModal } from './OnboardingErrorTrackingSourceMapsModal'
import { SourceMapOptionCard } from './source-maps/SourceMapOptionCard'
import { SourceMapStatus } from './source-maps/SourceMapStatus'
import { automatedSourceMapsTechnologies } from './source-maps/SourceMapsSDKInstructionsMap'
import { sourceMapsStepLogic } from './source-maps/sourceMapsStepLogic'

export function OnboardingErrorTrackingSourceMapsStep({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element {
    const { selectedOption, instructionsModalOpen, shouldShowContinue, shouldShowSourceMapStatus } =
        useValues(sourceMapsStepLogic)
    const { setSelectedOption, setInstructionsModalOpen } = useActions(sourceMapsStepLogic)

    const selectedSDK = selectedOption
        ? automatedSourceMapsTechnologies.find((sdk) => sdk.key === selectedOption)
        : null

    return (
        <OnboardingStep
            title="Link source maps"
            stepKey={stepKey}
            continueOverride={!shouldShowContinue ? <></> : undefined}
            showSkip={!shouldShowContinue}
        >
            <p>
                Some languages, bundlers and frameworks obfuscate code making debugging difficult. Source maps are
                essential to transform code back to the original source. Choose the option that matches your setup to
                ensure stack traces are readable.
            </p>

            <div className="space-y-3 mt-4">
                <SourceMapOptionCard
                    title="Unminified code"
                    description="Not all languages and frameworks are minified. For example Python and Node code often remains readable and there is no need to upload source maps."
                    optionKey="no-minification"
                    selectedOption={selectedOption}
                    onSelect={() => setSelectedOption('no-minification')}
                />

                <SourceMapOptionCard
                    title="Public source maps"
                    description="If source maps are publicly available PostHog can fetch and provide readable stack traces without any additional setup."
                    optionKey="public-source-maps"
                    selectedOption={selectedOption}
                    onSelect={() => setSelectedOption('public-source-maps')}
                />

                <SourceMapOptionCard
                    title="Upload source maps manually"
                    description="Should you wish to keep your source maps private you will need to upload source maps during your build process to see unminified code in your stack traces."
                    optionKey="cli"
                    selectedOption={selectedOption}
                    onSelect={() => setSelectedOption('cli')}
                >
                    <div className="mt-4 space-y-4">
                        <div>
                            <p className="text-sm mb-2">
                                The <code>posthog-cli</code> handles this process. You will need to install it.
                            </p>
                            <CodeSnippet language={Language.Bash}>
                                {[
                                    "curl --proto '=https' --tlsv1.2 -LsSf https://github.com/PostHog/posthog/releases/download/posthog-cli-v0.0.2/posthog-cli-installer.sh | sh",
                                    'posthog-cli-update',
                                ].join('\n')}
                            </CodeSnippet>
                            <p className="text-sm my-2">And complete the necessary authentication.</p>
                            <CodeSnippet language={Language.Bash}>posthog-cli login</CodeSnippet>
                        </div>
                        <div>
                            <p className="text-sm mb-2">
                                Once you've built your application and have bundled assets that serve your site, inject
                                the context required by PostHog to associate the maps with the served code. You will
                                then need to upload the modified assets to PostHog. Both of these operations can be done
                                by running the respective sourcemap commands.
                            </p>
                            <CodeSnippet language={Language.Bash}>
                                posthog-cli sourcemap process --directory ./path/to/assets
                            </CodeSnippet>
                        </div>
                    </div>
                </SourceMapOptionCard>
            </div>

            <div className="mt-6">
                <h3 className="text-lg font-semibold mb-4">Automatic source maps upload</h3>
                <p className="mb-4">
                    For some frameworks and languages, PostHog can automatically upload source maps during your build
                    process. Select your framework to see how to configure it.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                    {automatedSourceMapsTechnologies.map((sdk) => (
                        <LemonCard
                            key={sdk.key}
                            className={`p-4 cursor-pointer flex flex-col items-start justify-center border-2 ${selectedOption === sdk.key ? 'border-[var(--primary-3000-frame-bg-light)]' : 'border-transparent'}`}
                            onClick={() => {
                                setSelectedOption(sdk.key)
                                setInstructionsModalOpen(true)
                            }}
                        >
                            {typeof sdk.image === 'string' ? (
                                <img src={sdk.image} className="w-8 h-8 mb-2" alt={`${sdk.name} logo`} />
                            ) : typeof sdk.image === 'object' && 'default' in sdk.image ? (
                                <img src={sdk.image.default} className="w-8 h-8 mb-2" alt={`${sdk.name} logo`} />
                            ) : (
                                sdk.image
                            )}
                            <strong>{sdk.name}</strong>
                        </LemonCard>
                    ))}
                </div>
            </div>

            {selectedSDK && (
                <SourceMapsInstructionsModal
                    isOpen={instructionsModalOpen}
                    onClose={() => setInstructionsModalOpen(false)}
                    sdk={selectedSDK}
                />
            )}

            {shouldShowSourceMapStatus && <SourceMapStatus />}
        </OnboardingStep>
    )
}
