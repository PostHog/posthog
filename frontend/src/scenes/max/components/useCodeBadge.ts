import { useValues } from 'kea'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { CODE_BADGE } from '../suggestionTopics'

export interface CodeBadge {
    visible: boolean
    label: string
    introOpen: boolean
    openIntro: () => void
    closeIntro: () => void
}

export function useCodeBadge(): CodeBadge {
    const visible = useFeatureFlag('PRODUCT_AUTONOMY')
    const { featureFlags } = useValues(featureFlagLogic)
    // Intro-modal visibility is pure view state, so it stays local instead of in a logic
    const [introOpen, setIntroOpen] = useState(false)

    // Experiment: does labeling the badge by outcome beat the neutral "Code" for self-driving
    // setup? Short-circuit on the autonomy gate so the flag (and its exposure event) is only
    // evaluated for users who actually see the badge.
    const label =
        visible && featureFlags[FEATURE_FLAGS.CODE_BADGE_SELF_DRIVING_LABEL] === 'self-driving'
            ? 'Self-driving'
            : CODE_BADGE.label

    return {
        visible,
        label,
        introOpen,
        openIntro: () => setIntroOpen(true),
        closeIntro: () => setIntroOpen(false),
    }
}
