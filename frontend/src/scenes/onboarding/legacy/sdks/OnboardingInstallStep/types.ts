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
    /** Analytics hook for the copy-project-token button, for hosts with their own event vocabulary */
    onCopyProjectToken?: () => void
    showTopControls?: boolean
    installationComplete: boolean
    showTopSkipButton: boolean
}

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
