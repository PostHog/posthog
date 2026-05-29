import { MOCK_TEAM_ID } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    localStorageOverrideKey,
    localStorageProductKey,
    PromotedProductTarget,
    promotedProductLogic,
} from '~/layout/panel-layout/ai-first/promotedProductLogic'

import { ConfigurePromotedProductModal } from './ConfigurePromotedProductModal'

interface StoryArgs {
    onboardingIntent: string | null
    initialOverride: PromotedProductTarget | null
}

const PRODUCT_KEY = localStorageProductKey(MOCK_TEAM_ID)
const OVERRIDE_KEY = localStorageOverrideKey(MOCK_TEAM_ID)
const LOCAL_STORAGE_KEYS = [PRODUCT_KEY, OVERRIDE_KEY]

function StoryRunner({ onboardingIntent, initialOverride }: StoryArgs): JSX.Element | null {
    const [ready, setReady] = useState(false)

    useEffect(() => {
        for (const key of LOCAL_STORAGE_KEYS) {
            window.localStorage.removeItem(key)
        }
        if (onboardingIntent) {
            window.localStorage.setItem(PRODUCT_KEY, onboardingIntent)
        }
        if (initialOverride) {
            window.localStorage.setItem(OVERRIDE_KEY, JSON.stringify(initialOverride))
        }

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PROMOTED_PRODUCT], {
            [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent_plus',
        })

        const unmount = promotedProductLogic.mount()
        promotedProductLogic.actions.refreshIntentFromStorage()
        promotedProductLogic.actions.refreshOverrideFromStorage()
        setReady(true)

        return () => {
            for (const key of LOCAL_STORAGE_KEYS) {
                window.localStorage.removeItem(key)
            }
            featureFlagLogic.actions.setFeatureFlags([], {})
            unmount()
            setReady(false)
        }
    }, [onboardingIntent, initialOverride])

    if (!ready) {
        return null
    }

    return <ConfigurePromotedProductModal isOpen={true} onClose={() => undefined} />
}

const meta: Meta<StoryArgs> = {
    title: 'Layout/Configure Promoted Product Modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    argTypes: {
        onboardingIntent: {
            control: { type: 'select' },
            options: [null, 'product_analytics', 'session_replay', 'web_analytics', 'error_tracking', 'llm_analytics'],
        },
    },
    render: (args) => <StoryRunner {...args} />,
}
export default meta

type Story = StoryObj<StoryArgs>

export const InitialFromOnboardingProduct: Story = {
    args: {
        onboardingIntent: 'session_replay',
        initialOverride: null,
    },
}

export const InitialFromUrlOverride: Story = {
    args: {
        onboardingIntent: 'session_replay',
        initialOverride: { kind: 'url', value: '/my-dashboard' },
    },
}

export const InitialFromAiChatOverride: Story = {
    args: {
        onboardingIntent: 'session_replay',
        initialOverride: { kind: 'ai_chat', value: 'ai_chat' },
    },
}

export const NoOnboardingIntent: Story = {
    args: {
        onboardingIntent: null,
        initialOverride: null,
    },
}
