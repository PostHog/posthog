import { MOCK_TEAM_ID } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    localStorageOverrideKey,
    localStorageProductKey,
    PromotedProductTarget,
    PromotedProductVariant,
    promotedProductLogic,
} from './promotedProductLogic'
import { PromotedProductNavItem } from './PromotedProductNavItem'

interface StoryArgs {
    variant: PromotedProductVariant | 'unset'
    onboardingIntent: string | null
    override: PromotedProductTarget | null
    isCollapsed: boolean
}

const PRODUCT_KEY = localStorageProductKey(MOCK_TEAM_ID)
const OVERRIDE_KEY = localStorageOverrideKey(MOCK_TEAM_ID)
const LOCAL_STORAGE_KEYS = [PRODUCT_KEY, OVERRIDE_KEY]

/** Sidebar-shaped wrapper so the nav item renders against the same Tailwind context it would on the real left rail. */
function SidebarWrapper({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="w-64 bg-surface-primary border border-border rounded p-2">
            <div className="text-xs text-muted px-2 pb-2">Project nav (preview)</div>
            {children}
        </div>
    )
}

function StoryRunner({ variant, onboardingIntent, override, isCollapsed }: StoryArgs): JSX.Element | null {
    const [ready, setReady] = useState(false)

    useEffect(() => {
        for (const key of LOCAL_STORAGE_KEYS) {
            window.localStorage.removeItem(key)
        }
        if (onboardingIntent) {
            window.localStorage.setItem(PRODUCT_KEY, onboardingIntent)
        }
        if (override) {
            window.localStorage.setItem(OVERRIDE_KEY, JSON.stringify(override))
        }

        if (variant === 'unset') {
            featureFlagLogic.actions.setFeatureFlags([], {})
        } else {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PROMOTED_PRODUCT], {
                [FEATURE_FLAGS.PROMOTED_PRODUCT]: variant,
            })
        }

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
    }, [variant, onboardingIntent, override])

    if (!ready) {
        return null
    }

    return (
        <SidebarWrapper>
            <PromotedProductNavItem isCollapsed={isCollapsed} />
        </SidebarWrapper>
    )
}

const meta: Meta<StoryArgs> = {
    title: 'Layout/Promoted Product Nav Item',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    argTypes: {
        variant: {
            control: { type: 'select' },
            options: ['unset', 'control_a', 'control_b', 'intent', 'intent_plus'],
        },
        onboardingIntent: {
            control: { type: 'select' },
            options: [
                null,
                'product_analytics',
                'session_replay',
                'web_analytics',
                'error_tracking',
                'llm_analytics',
                'feature_flags',
            ],
        },
        isCollapsed: { control: 'boolean' },
    },
    render: (args) => <StoryRunner {...args} />,
}
export default meta

type Story = StoryObj<StoryArgs>

export const ControlAHidden: Story = {
    args: {
        variant: 'control_a',
        onboardingIntent: 'session_replay',
        override: null,
        isCollapsed: false,
    },
}

export const ControlBHidden: Story = {
    args: {
        variant: 'control_b',
        onboardingIntent: 'session_replay',
        override: null,
        isCollapsed: false,
    },
}

export const IntentShowsOnboardingPick: Story = {
    args: {
        variant: 'intent',
        onboardingIntent: 'session_replay',
        override: null,
        isCollapsed: false,
    },
}

export const IntentWithProductAnalytics: Story = {
    args: {
        variant: 'intent',
        onboardingIntent: 'product_analytics',
        override: null,
        isCollapsed: false,
    },
}

export const IntentNoOnboardingPickHidden: Story = {
    args: {
        variant: 'intent',
        onboardingIntent: null,
        override: null,
        isCollapsed: false,
    },
}

export const IntentPlusShowsCog: Story = {
    args: {
        variant: 'intent_plus',
        onboardingIntent: 'session_replay',
        override: null,
        isCollapsed: false,
    },
}

export const IntentPlusWithUrlOverride: Story = {
    args: {
        variant: 'intent_plus',
        onboardingIntent: 'session_replay',
        override: { kind: 'url', value: '/my-dashboard' },
        isCollapsed: false,
    },
}

export const IntentPlusWithAiChatOverride: Story = {
    args: {
        variant: 'intent_plus',
        onboardingIntent: 'session_replay',
        override: { kind: 'ai_chat', value: 'ai_chat' },
        isCollapsed: false,
    },
}

export const IntentCollapsedSidebar: Story = {
    args: {
        variant: 'intent',
        onboardingIntent: 'web_analytics',
        override: null,
        isCollapsed: true,
    },
}

export const FlagUnsetHidden: Story = {
    args: {
        variant: 'unset',
        onboardingIntent: 'session_replay',
        override: null,
        isCollapsed: false,
    },
}
