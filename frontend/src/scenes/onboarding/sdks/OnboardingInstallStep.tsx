import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconCopy, IconTerminal } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonInput,
    LemonModal,
    LemonTabs,
    SpinnerOverlay,
} from '@posthog/lemon-ui'

import { InviteMembersButton } from 'lib/components/Account/InviteMembersButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { OnboardingStepKey, type SDK, SDKInstructionsMap, SDKTag, SDKTagOverrides } from '~/types'

import { OnboardingStepComponentType, onboardingLogic } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { type AdblockDetectionResult, useAdblockDetection } from './hooks/useAdblockDetection'
import { useInstallationComplete } from './hooks/useInstallationComplete'
import { AdblockWarning, RealtimeCheckIndicator } from './RealtimeCheckIndicator'
import { useWizardCommand } from './sdk-install-instructions/components/SetupWizardBanner'
import { sdksLogic } from './sdksLogic'
import { SDKSnippet } from './SDKSnippet'

interface SDKInstructionsModalProps {
    isOpen: boolean
    onClose: () => void
    sdk?: SDK
    sdkInstructionMap: SDKInstructionsMap
    adblockResult: AdblockDetectionResult
    verifyingProperty?: string
    verifyingName?: string
}

export function SDKInstructionsModal({
    isOpen,
    onClose,
    sdk,
    sdkInstructionMap,
    adblockResult,
    verifyingProperty = 'ingested_event',
    verifyingName = 'event',
}: SDKInstructionsModalProps): JSX.Element {
    const installationComplete = useInstallationComplete(verifyingProperty)

    const sdkInstructions = sdkInstructionMap[sdk?.key as keyof typeof sdkInstructionMap] as
        | (() => JSX.Element)
        | undefined

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} simple title="">
            {!sdk?.key || !sdkInstructions ? (
                <SpinnerOverlay />
            ) : (
                <div className="flex flex-col h-full">
                    <header className="p-4 flex items-center gap-2">
                        <LemonButton icon={<IconArrowLeft />} onClick={onClose} size="xsmall">
                            All SDKs
                        </LemonButton>
                    </header>
                    <div className="flex-grow overflow-y-auto px-4 py-2">
                        <SDKSnippet sdk={sdk} sdkInstructions={sdkInstructions} />
                    </div>
                    {!installationComplete && (
                        <div className="px-4 py-2">
                            <AdblockWarning adblockResult={adblockResult} />
                        </div>
                    )}
                    <footer className="sticky bottom-0 w-full bg-bg-light dark:bg-bg-depth rounded-b-sm p-2 flex justify-between items-center gap-2 px-4">
                        <RealtimeCheckIndicator
                            teamPropertyToVerify={verifyingProperty}
                            listeningForName={verifyingName}
                        />
                        <NextButton installationComplete={installationComplete} />
                    </footer>
                </div>
            )}
        </LemonModal>
    )
}

// Supported wizard frameworks for display
const WIZARD_FRAMEWORKS = [
    'Next.js',
    'React',
    'Angular',
    'Vue',
    'Nuxt',
    'Astro',
    'SvelteKit',
    'Django',
    'Flask',
    'Laravel',
    'React Native',
    'iOS',
    'Android',
    'Ruby on Rails',
    'React Router',
    'Python',
]

const WIZARD_GRADIENT_STYLE: React.CSSProperties = {
    color: 'transparent',
    WebkitBackgroundClip: 'text',
    backgroundClip: 'text',
    backgroundImage:
        'linear-gradient(90deg, #0143cb 0%, #2b6ff4 24%, #d23401 47%, #ff651f 66%, #fba000 83%, #0143cb 100%)',
    backgroundSize: '200% 100%',
    animation: 'wizard-gradient-scroll 3s linear infinite',
}

const WIZARD_FLASH_STYLE: React.CSSProperties = {
    ...WIZARD_GRADIENT_STYLE,
    color: '#36C46F',
    backgroundImage: 'none',
    WebkitBackgroundClip: 'unset',
    backgroundClip: 'unset',
    animation: 'wizard-copied-flash 1500ms ease-out forwards',
    position: 'absolute',
    inset: 0,
    pointerEvents: 'none',
}

const WIZARD_HOG_URL = 'https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png'

function WizardCommandBlock(): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const [copyKey, setCopyKey] = useState(0)

    if (!isCloudOrDev) {
        return <></>
    }

    const handleCopy = (): void => {
        void copyToClipboard(wizardCommand, 'Wizard command')
        setCopyKey((k) => k + 1)
    }

    return (
        <div className="flex flex-col gap-3">
            {/* Inject keyframe animations */}
            <style>{`
                @keyframes wizard-gradient-scroll {
                    0% { background-position-x: 0%; }
                    100% { background-position-x: 200%; }
                }
                @keyframes wizard-copied-flash {
                    0%, 50% { opacity: 1; }
                    100% { opacity: 0; }
                }
                @keyframes wizard-copy-bounce {
                    0% { transform: scale(1); }
                    15% { transform: scale(0.96); }
                    40% { transform: scale(1.03); }
                    70% { transform: scale(0.99); }
                    100% { transform: scale(1); }
                }
                @keyframes wizard-hog-cast {
                    0% { transform: rotate(0deg); }
                    20% { transform: rotate(-8deg); }
                    50% { transform: rotate(5deg); }
                    80% { transform: rotate(-2deg); }
                    100% { transform: rotate(0deg); }
                }
            `}</style>

            <div className="flex gap-6">
                <img
                    key={`hog-${copyKey}`}
                    src={WIZARD_HOG_URL}
                    alt="PostHog wizard hedgehog"
                    className="w-28 h-28 hidden sm:block shrink-0 self-center"
                    style={copyKey > 0 ? { animation: 'wizard-hog-cast 500ms ease-out' } : undefined}
                />
                <div className="flex-1 flex flex-col gap-3">
                    <button
                        onClick={handleCopy}
                        key={`btn-${copyKey}`}
                        className="group inline-flex items-center gap-2 bg-bg-light border border-border font-mono text-sm px-4 py-3 rounded-lg cursor-pointer hover:border-primary transition-colors w-fit"
                        style={copyKey > 0 ? { animation: 'wizard-copy-bounce 400ms ease-out' } : undefined}
                    >
                        <IconTerminal className="size-4 text-muted" />
                        <span className="relative">
                            <code style={WIZARD_GRADIENT_STYLE} className="!bg-transparent !p-0 !border-0 select-all">
                                {wizardCommand}
                            </code>
                            {copyKey > 0 && (
                                <code
                                    key={copyKey}
                                    style={WIZARD_FLASH_STYLE}
                                    className="!bg-transparent !p-0 !border-0"
                                    aria-hidden="true"
                                >
                                    {wizardCommand}
                                </code>
                            )}
                        </span>
                        <IconCopy className="size-4 text-muted group-hover:text-primary" />
                    </button>

                    <p className="text-xs text-muted mb-0">
                        Auto-detects your framework, installs the SDK, and sets up event capture.
                    </p>

                    <div className="flex flex-wrap gap-1.5">
                        <span className="text-xs text-muted">Supports:</span>
                        {WIZARD_FRAMEWORKS.map((fw) => (
                            <span
                                key={fw}
                                className="text-xs text-muted bg-bg-light border border-border rounded px-1.5 py-0.5"
                            >
                                {fw}
                            </span>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}

interface SDKGridProps {
    filteredSDKs: SDK[]
    searchTerm: string
    selectedTag: SDKTag | null
    tags: string[]
    onSDKClick: (sdk: SDK) => void
    onSearchChange: (term: string) => void
    onTagChange: (tag: SDKTag | null) => void
    currentTeam: { api_token?: string } | null
    showTopControls?: boolean
    installationComplete: boolean
    showTopSkipButton: boolean
}

function SDKGrid({
    filteredSDKs,
    searchTerm,
    selectedTag,
    tags,
    onSDKClick,
    onSearchChange,
    onTagChange,
    currentTeam,
    showTopControls = true,
    installationComplete,
    showTopSkipButton,
}: SDKGridProps): JSX.Element {
    return (
        <div className="flex flex-col gap-y-4">
            <div className="flex flex-col gap-y-2">
                {showTopControls && (
                    <div className="flex flex-col-reverse md:flex-row justify-between gap-4">
                        <LemonInput
                            value={searchTerm}
                            onChange={onSearchChange}
                            placeholder="Search"
                            className="w-full max-w-[220px]"
                        />
                        <div className="flex flex-row flex-wrap gap-2">
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={() => void copyToClipboard(currentTeam?.api_token || '', 'Project token')}
                                icon={<IconCopy />}
                                data-attr="copy-project-token"
                            >
                                Copy project token
                            </LemonButton>
                            <InviteMembersButton
                                type="primary"
                                size="small"
                                fullWidth={false}
                                text="Invite developer"
                            />
                            {showTopSkipButton && (
                                <NextButton size="small" installationComplete={installationComplete} />
                            )}
                        </div>
                    </div>
                )}
                <LemonTabs
                    activeKey={selectedTag ?? 'All'}
                    onChange={(key) => onTagChange(key === 'All' ? null : (key as SDKTag))}
                    tabs={tags.map((tag) => ({
                        key: tag,
                        label: tag,
                    }))}
                />
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                    {(filteredSDKs ?? []).map((sdk) => (
                        <LemonCard
                            key={sdk.key}
                            className="p-4 cursor-pointer flex flex-col items-start justify-center"
                            onClick={() => onSDKClick(sdk)}
                        >
                            <div className="w-8 h-8 mb-2">
                                {typeof sdk.image === 'string' ? (
                                    <img src={sdk.image} className="w-8 h-8" alt={`${sdk.name} logo`} />
                                ) : typeof sdk.image === 'object' && 'default' in sdk.image ? (
                                    <img src={sdk.image.default} className="w-8 h-8" alt={`${sdk.name} logo`} />
                                ) : (
                                    sdk.image
                                )}
                            </div>

                            <strong>{sdk.name}</strong>
                        </LemonCard>
                    ))}

                    {searchTerm && (
                        <LemonCard className="p-4 cursor-pointer flex flex-col items-start justify-center col-span-1 sm:col-span-2">
                            <div className="flex flex-col items-start gap-2">
                                <span className="mb-2 text-muted">
                                    Don&apos;t see your SDK listed? We are always looking to expand our list of
                                    supported SDKs.
                                </span>
                                <LemonButton
                                    data-attr="onboarding-reach-out-to-us-button"
                                    type="secondary"
                                    size="small"
                                    targetBlank
                                >
                                    Reach out to us
                                </LemonButton>
                            </div>
                        </LemonCard>
                    )}
                </div>
            </div>
        </div>
    )
}

// =====================================================
// Variant A: wizard-hero - Hero Card Above SDK Grid
// =====================================================

function WizardHeroVariant({
    sdkGridProps,
    adblockResult,
    installationComplete,
    listeningForName,
    teamPropertyToVerify,
    header,
}: VariantProps): JSX.Element {
    return (
        <OnboardingStep
            title="Install"
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={!installationComplete ? 'Installation is not complete' : undefined}
            showSkip={!installationComplete}
            actions={
                <div className="pr-2">
                    <RealtimeCheckIndicator
                        teamPropertyToVerify={teamPropertyToVerify}
                        listeningForName={listeningForName}
                    />
                </div>
            }
        >
            {header}
            {!installationComplete && <AdblockWarning adblockResult={adblockResult} />}
            <div className="mt-6 space-y-6">
                <LemonBanner type="info" hideIcon>
                    <div className="p-2">
                        <h3 className="text-lg font-bold mb-1">Install PostHog with one command</h3>
                        <p className="text-sm mb-4">
                            The AI wizard auto-detects your framework and sets everything up. Just paste this into your
                            terminal.
                        </p>
                        <WizardCommandBlock />
                    </div>
                </LemonBanner>

                <div className="flex items-center gap-3">
                    <div className="flex-1 border-t border-border" />
                    <span className="text-muted font-semibold text-xs uppercase">Or, set up manually</span>
                    <div className="flex-1 border-t border-border" />
                </div>

                <SDKGrid {...sdkGridProps} />
            </div>
        </OnboardingStep>
    )
}

// =====================================================
// Variant B: wizard-tab - Tabbed Interface
// =====================================================

function WizardTabVariant({
    sdkGridProps,
    adblockResult,
    installationComplete,
    listeningForName,
    teamPropertyToVerify,
    header,
}: VariantProps): JSX.Element {
    const [activeTab, setActiveTab] = useState<string>('wizard')

    return (
        <OnboardingStep
            title="Install"
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={!installationComplete ? 'Installation is not complete' : undefined}
            showSkip={!installationComplete}
            actions={
                <div className="pr-2">
                    <RealtimeCheckIndicator
                        teamPropertyToVerify={teamPropertyToVerify}
                        listeningForName={listeningForName}
                    />
                </div>
            }
        >
            {header}
            {!installationComplete && <AdblockWarning adblockResult={adblockResult} />}
            <div className="mt-6">
                <LemonTabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    tabs={[
                        {
                            key: 'wizard',
                            label: (
                                <span className="flex items-center gap-1.5">
                                    AI wizard
                                    <span className="bg-success-highlight text-success text-[10px] font-bold px-1.5 py-0.5 rounded-sm uppercase">
                                        Recommended
                                    </span>
                                </span>
                            ),
                        },
                        {
                            key: 'manual',
                            label: 'Manual setup',
                        },
                    ]}
                />

                {activeTab === 'wizard' ? (
                    <div className="mt-4 space-y-6">
                        <div>
                            <h3 className="text-base font-semibold mb-2">Install PostHog automatically</h3>
                            <p className="text-sm text-muted mb-4">
                                Run this command in your project directory. The wizard will detect your framework,
                                install the SDK, and configure event capture.
                            </p>
                        </div>
                        <WizardCommandBlock />
                    </div>
                ) : (
                    <div className="mt-4">
                        <SDKGrid {...sdkGridProps} />
                    </div>
                )}
            </div>
        </OnboardingStep>
    )
}

// =====================================================
// Variant C: wizard-only - Wizard-Focused View
// =====================================================

function WizardOnlyVariant({
    sdkGridProps,
    sdkInstructionMap,
    adblockResult,
    installationComplete,
    listeningForName,
    teamPropertyToVerify,
    selectedSDK,
    header,
}: VariantProps): JSX.Element {
    const [manualModalOpen, setManualModalOpen] = useState(false)
    const [sdkInstructionsOpen, setSdkInstructionsOpen] = useState(false)

    const handleWizardOnlySDKClick = (sdk: SDK): void => {
        sdkGridProps.onSDKClick(sdk)
        setSdkInstructionsOpen(true)
    }

    return (
        <OnboardingStep
            title="Install"
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={!installationComplete ? 'Installation is not complete' : undefined}
            showSkip={!installationComplete}
            actions={
                <div className="pr-2">
                    <RealtimeCheckIndicator
                        teamPropertyToVerify={teamPropertyToVerify}
                        listeningForName={listeningForName}
                    />
                </div>
            }
        >
            {header}
            {!installationComplete && <AdblockWarning adblockResult={adblockResult} />}
            <div className="mt-6 space-y-8">
                <div className="text-center max-w-lg mx-auto">
                    <h2 className="text-2xl font-bold mb-2">Install PostHog with one command</h2>
                    <p className="text-muted">
                        Our AI wizard detects your framework, installs the right SDK, and configures event capture
                        automatically.
                    </p>
                </div>

                <div className="max-w-xl mx-auto">
                    <WizardCommandBlock />
                </div>

                <div className="text-center">
                    <LemonButton type="tertiary" size="small" onClick={() => setManualModalOpen(true)}>
                        Need to set up manually?
                    </LemonButton>
                </div>
            </div>

            <LemonModal
                isOpen={manualModalOpen}
                onClose={() => setManualModalOpen(false)}
                title="Manual SDK setup"
                width="80vw"
            >
                <div className="p-4">
                    <SDKGrid {...{ ...sdkGridProps, onSDKClick: handleWizardOnlySDKClick }} showTopControls />
                </div>
            </LemonModal>

            {selectedSDK && (
                <SDKInstructionsModal
                    isOpen={sdkInstructionsOpen && !manualModalOpen}
                    onClose={() => {
                        setSdkInstructionsOpen(false)
                        setManualModalOpen(true)
                    }}
                    sdk={selectedSDK}
                    sdkInstructionMap={sdkInstructionMap}
                    adblockResult={adblockResult}
                    verifyingProperty={teamPropertyToVerify}
                    verifyingName={listeningForName}
                />
            )}
        </OnboardingStep>
    )
}

// =====================================================
// Main Component with Feature Flag Routing
// =====================================================

interface OnboardingInstallStepProps {
    sdkInstructionMap: SDKInstructionsMap
    sdkTagOverrides?: SDKTagOverrides
    listeningForName?: string
    teamPropertyToVerify?: string
    header?: React.ReactNode
}

interface VariantProps {
    sdkGridProps: SDKGridProps
    sdkInstructionMap: SDKInstructionsMap
    adblockResult: AdblockDetectionResult
    installationComplete: boolean
    listeningForName: string
    teamPropertyToVerify: string
    selectedSDK: SDK | null
    header?: React.ReactNode
}

export const OnboardingInstallStep: OnboardingStepComponentType<OnboardingInstallStepProps> = ({
    sdkInstructionMap,
    sdkTagOverrides,
    listeningForName = 'event',
    teamPropertyToVerify = 'ingested_event',
    header,
}) => {
    const { setAvailableSDKInstructionsMap, setSDKTagOverrides, selectSDK, setSearchTerm, setSelectedTag } =
        useActions(sdksLogic)
    const { filteredSDKs, selectedSDK, tags, searchTerm, selectedTag } = useValues(sdksLogic)
    const [instructionsModalOpen, setInstructionsModalOpen] = useState(false)
    const { currentTeam } = useValues(teamLogic)

    const installationComplete = useInstallationComplete(teamPropertyToVerify)
    const adblockResult = useAdblockDetection()
    const isSkipButtonExperiment = useFeatureFlag('ONBOARDING_SKIP_INSTALL_STEP', 'test')

    const isWizardHero = useFeatureFlag('ONBOARDING_WIZARD_PROMINENCE', 'wizard-hero')
    const isWizardTab = useFeatureFlag('ONBOARDING_WIZARD_PROMINENCE', 'wizard-tab')
    const isWizardOnly = useFeatureFlag('ONBOARDING_WIZARD_PROMINENCE', 'wizard-only')

    useEffect(() => {
        setSDKTagOverrides(sdkTagOverrides ?? {})
        setAvailableSDKInstructionsMap(sdkInstructionMap)
    }, [sdkInstructionMap, sdkTagOverrides, setAvailableSDKInstructionsMap, setSDKTagOverrides])

    const showSkipAtBottom = isSkipButtonExperiment && !installationComplete
    const showTopSkipButton = !isSkipButtonExperiment || installationComplete

    const handleSDKClick = (sdk: SDK): void => {
        selectSDK(sdk)
        setInstructionsModalOpen(true)
    }

    const isWizardVariant = isWizardHero || isWizardTab || isWizardOnly

    const sdkGridProps: SDKGridProps = {
        filteredSDKs: filteredSDKs ?? [],
        searchTerm,
        selectedTag,
        tags,
        onSDKClick: handleSDKClick,
        onSearchChange: setSearchTerm,
        onTagChange: setSelectedTag,
        currentTeam,
        showTopControls: true,
        installationComplete,
        showTopSkipButton: isWizardVariant ? false : showTopSkipButton,
    }

    const variantProps: VariantProps = {
        sdkGridProps,
        sdkInstructionMap,
        adblockResult,
        installationComplete,
        listeningForName,
        teamPropertyToVerify,
        selectedSDK,
        header,
    }

    // Route to the appropriate variant
    if (isWizardHero) {
        return (
            <>
                <WizardHeroVariant {...variantProps} />
                {selectedSDK && (
                    <SDKInstructionsModal
                        isOpen={instructionsModalOpen}
                        onClose={() => setInstructionsModalOpen(false)}
                        sdk={selectedSDK}
                        sdkInstructionMap={sdkInstructionMap}
                        adblockResult={adblockResult}
                        verifyingProperty={teamPropertyToVerify}
                        verifyingName={listeningForName}
                    />
                )}
            </>
        )
    }

    if (isWizardTab) {
        return (
            <>
                <WizardTabVariant {...variantProps} />
                {selectedSDK && (
                    <SDKInstructionsModal
                        isOpen={instructionsModalOpen}
                        onClose={() => setInstructionsModalOpen(false)}
                        sdk={selectedSDK}
                        sdkInstructionMap={sdkInstructionMap}
                        adblockResult={adblockResult}
                        verifyingProperty={teamPropertyToVerify}
                        verifyingName={listeningForName}
                    />
                )}
            </>
        )
    }

    if (isWizardOnly) {
        return <WizardOnlyVariant {...variantProps} />
    }

    // Control: existing behavior
    return (
        <OnboardingStep
            title="Install"
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={!installationComplete ? 'Installation is not complete' : undefined}
            showSkip={showSkipAtBottom}
            actions={
                <div className="pr-2">
                    <RealtimeCheckIndicator
                        teamPropertyToVerify={teamPropertyToVerify}
                        listeningForName={listeningForName}
                    />
                </div>
            }
        >
            {header}
            {!installationComplete && <AdblockWarning adblockResult={adblockResult} />}
            <div className="flex flex-col gap-y-4 mt-6">
                <div className="flex flex-col gap-y-2">
                    <div className="flex flex-col-reverse md:flex-row justify-between gap-4">
                        <LemonInput
                            value={searchTerm}
                            onChange={setSearchTerm}
                            placeholder="Search"
                            className="w-full max-w-[220px]"
                        />
                        <div className="flex flex-row flex-wrap gap-2">
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={() => void copyToClipboard(currentTeam?.api_token || '', 'Project token')}
                                icon={<IconCopy />}
                                data-attr="copy-project-token"
                            >
                                Copy project token
                            </LemonButton>
                            <InviteMembersButton
                                type="primary"
                                size="small"
                                fullWidth={false}
                                text="Invite developer"
                            />
                            {showTopSkipButton && (
                                <NextButton size="small" installationComplete={installationComplete} />
                            )}
                        </div>
                    </div>
                    <LemonTabs
                        activeKey={selectedTag ?? 'All'}
                        onChange={(key) => setSelectedTag(key === 'All' ? null : (key as SDKTag))}
                        tabs={tags.map((tag) => ({
                            key: tag,
                            label: tag,
                        }))}
                    />
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                        {(filteredSDKs ?? []).map((sdk) => (
                            <LemonCard
                                key={sdk.key}
                                className="p-4 cursor-pointer flex flex-col items-start justify-center"
                                onClick={() => {
                                    selectSDK(sdk)
                                    setInstructionsModalOpen(true)
                                }}
                            >
                                <div className="w-8 h-8 mb-2">
                                    {typeof sdk.image === 'string' ? (
                                        <img src={sdk.image} className="w-8 h-8" alt={`${sdk.name} logo`} />
                                    ) : typeof sdk.image === 'object' && 'default' in sdk.image ? (
                                        <img src={sdk.image.default} className="w-8 h-8" alt={`${sdk.name} logo`} />
                                    ) : (
                                        sdk.image
                                    )}
                                </div>

                                <strong>{sdk.name}</strong>
                            </LemonCard>
                        ))}

                        {/* This will open a survey to collect feedback on the SDKs we don't support yet */}
                        {/* https://us.posthog.com/project/2/surveys/019b47ab-5f19-0000-7f31-4f9681cde589 */}
                        {searchTerm && (
                            <LemonCard className="p-4 cursor-pointer flex flex-col items-start justify-center col-span-1 sm:col-span-2">
                                <div className="flex flex-col items-start gap-2">
                                    <span className="mb-2 text-muted">
                                        Don&apos;t see your SDK listed? We are always looking to expand our list of
                                        supported SDKs.
                                    </span>
                                    <LemonButton
                                        data-attr="onboarding-reach-out-to-us-button"
                                        type="secondary"
                                        size="small"
                                        targetBlank
                                    >
                                        Reach out to us
                                    </LemonButton>
                                </div>
                            </LemonCard>
                        )}
                    </div>
                </div>
            </div>

            {selectedSDK && (
                <SDKInstructionsModal
                    isOpen={instructionsModalOpen}
                    onClose={() => setInstructionsModalOpen(false)}
                    sdk={selectedSDK}
                    sdkInstructionMap={sdkInstructionMap}
                    adblockResult={adblockResult}
                    verifyingProperty={teamPropertyToVerify}
                    verifyingName={listeningForName}
                />
            )}
        </OnboardingStep>
    )
}

OnboardingInstallStep.stepKey = OnboardingStepKey.INSTALL

interface NextButtonProps {
    installationComplete: boolean
    size?: 'small' | 'medium'
}

const NextButton = ({ installationComplete, size = 'medium' }: NextButtonProps): JSX.Element => {
    const { hasNextStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep } = useActions(onboardingLogic)
    const { reportOnboardingStepCompleted, reportOnboardingStepSkipped } = useActions(eventUsageLogic)

    const advance = !hasNextStep ? completeOnboarding : goToNextStep
    const skipInstallation = (): void => {
        reportOnboardingStepSkipped(OnboardingStepKey.INSTALL)
        advance()
    }

    const continueInstallation = (): void => {
        reportOnboardingStepCompleted(OnboardingStepKey.INSTALL)
        advance()
    }

    if (!installationComplete) {
        return (
            <LemonButton type="secondary" size={size} onClick={skipInstallation}>
                Skip installation
            </LemonButton>
        )
    }

    return (
        <LemonButton
            data-attr="sdk-continue"
            sideIcon={hasNextStep ? <IconArrowRight /> : null}
            type="primary"
            status="alt"
            onClick={continueInstallation}
        >
            Next
        </LemonButton>
    )
}
