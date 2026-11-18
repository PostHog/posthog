import { useState } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

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
    // Intro-modal visibility is pure view state, so it stays local instead of in a logic
    const [introOpen, setIntroOpen] = useState(false)

    return {
        visible,
        label: CODE_BADGE.label,
        introOpen,
        openIntro: () => setIntroOpen(true),
        closeIntro: () => setIntroOpen(false),
    }
}
