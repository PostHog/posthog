import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useAdblockDetection } from 'scenes/onboarding/legacy/sdks/hooks/useAdblockDetection'
import { SDKGrid } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep/SDKGrid'
import { AdblockWarning } from 'scenes/onboarding/legacy/sdks/RealtimeCheckIndicator'
import { sdksLogic } from 'scenes/onboarding/legacy/sdks/sdksLogic'
import { SDKSnippet } from 'scenes/onboarding/legacy/sdks/SDKSnippet'
import { teamLogic } from 'scenes/teamLogic'

import { SDK, SDKKey } from '~/types'

import { QuickstartProduct } from '../../quickstartLogic'
import { captureQuickstartAction } from '../captureQuickstartAction'
import { PRODUCT_SDK_SETUP } from '../productSdkSetup'

export function ToolSetupModalContent({
    product,
    installationComplete,
}: {
    product: QuickstartProduct
    installationComplete: boolean
}): JSX.Element {
    const setup = PRODUCT_SDK_SETUP[product.key]
    const { filteredSDKs, selectedSDK, tags, searchTerm, selectedTag } = useValues(sdksLogic)
    const {
        setAvailableSDKInstructionsMap,
        setSDKDocsLinkOverrides,
        setSDKTagOverrides,
        selectSDK,
        setSelectedSDK,
        setSearchTerm,
        setSelectedTag,
    } = useActions(sdksLogic)
    const { currentTeam } = useValues(teamLogic)
    const adblockResult = useAdblockDetection()

    useEffect(() => {
        setSDKDocsLinkOverrides(setup?.docsLinkOverrides ?? {})
        setSDKTagOverrides(setup?.tagOverrides ?? {})
        setAvailableSDKInstructionsMap(setup?.instructionsMap ?? {})
        setSelectedSDK(null)
    }, [setup, setAvailableSDKInstructionsMap, setSDKDocsLinkOverrides, setSDKTagOverrides, setSelectedSDK])

    if (!setup) {
        return <p className="text-secondary mb-0">Follow the setup guide to get {product.name} running.</p>
    }

    if (!selectedSDK) {
        return (
            <SDKGrid
                filteredSDKs={filteredSDKs ?? []}
                searchTerm={searchTerm}
                selectedTag={selectedTag}
                tags={tags}
                onSDKClick={(sdk: SDK) => {
                    captureQuickstartAction('select_sdk', product.key, { sdk_key: sdk.key })
                    selectSDK(sdk)
                }}
                onSearchChange={setSearchTerm}
                onTagChange={setSelectedTag}
                currentTeam={currentTeam}
                showTopControls
                installationComplete={installationComplete}
                showTopSkipButton={false}
            />
        )
    }

    const instructions = setup.instructionsMap[selectedSDK.key as SDKKey] as (() => JSX.Element) | undefined

    return (
        <div className="flex flex-col gap-3">
            <div>
                <LemonButton
                    icon={<IconArrowLeft />}
                    size="xsmall"
                    onClick={() => {
                        captureQuickstartAction('view_all_sdks', product.key, { sdk_key: selectedSDK.key })
                        setSelectedSDK(null)
                    }}
                    data-attr="quickstart-sdk-back"
                >
                    All SDKs
                </LemonButton>
            </div>
            {instructions ? (
                <SDKSnippet sdk={selectedSDK} sdkInstructions={instructions} />
            ) : (
                <p className="text-secondary mb-0">Instructions for this SDK live in the full setup guide.</p>
            )}
            <AdblockWarning adblockResult={adblockResult} />
        </div>
    )
}
