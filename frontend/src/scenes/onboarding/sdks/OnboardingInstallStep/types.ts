import { type SDK, SDKInstructionsMap, SDKTag } from '~/types'

import { type AdblockDetectionResult } from '../hooks/useAdblockDetection'

export interface SDKGridProps {
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

/**
 * Props passed to every experiment variant. Not every variant reads every field:
 * WizardHero and WizardTab ignore `sdkInstructionMap` and `selectedSDK` because the
 * shared SDKInstructionsModal in the parent handles instruction rendering for them.
 * WizardOnly owns its own modal and therefore consumes both.
 */
export interface VariantProps {
    sdkGridProps: SDKGridProps
    sdkInstructionMap: SDKInstructionsMap
    adblockResult: AdblockDetectionResult
    installationComplete: boolean
    listeningForName: string
    teamPropertyToVerify: string
    selectedSDK: SDK | null
    header?: React.ReactNode
}
