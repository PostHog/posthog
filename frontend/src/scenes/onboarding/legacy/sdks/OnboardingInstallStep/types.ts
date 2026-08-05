import type { WizardBadgeItem } from 'scenes/onboarding/shared/wizard-sync/WizardModeShell'

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

/** Points the wizard block at a dedicated program (e.g. `ai-observability`) instead of the plain SDK install. */
export interface WizardOverrides {
    /** Wizard subcommand, e.g. `ai-observability`. */
    subcommand: string
    /** Replaces the default "what this does" line under the command. */
    description: React.ReactNode
    /** Replaces the intro paragraph above the command block. */
    intro?: string
    /** Replaces the framework "Supports:" badges (e.g. LLM providers). */
    supports?: WizardBadgeItem[]
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
    wizardOverrides?: WizardOverrides
}
