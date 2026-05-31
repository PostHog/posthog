import { MOCK_TEAM_ID } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import {
    localStorageOverrideKey,
    localStorageProductKey,
    PromotedProductTarget,
    promotedProductLogic,
} from './promotedProductLogic'
import { PromotedProductNavItem } from './PromotedProductNavItem'

interface StoryArgs {
    onboardingIntent: string | null
    override: PromotedProductTarget | null
    isCollapsed: boolean
}

const PRODUCT_KEY = localStorageProductKey(MOCK_TEAM_ID)
const OVERRIDE_KEY = localStorageOverrideKey(MOCK_TEAM_ID)

/** Sidebar-shaped wrapper so the nav item renders against the same Tailwind context it would on the real left rail. */
function SidebarWrapper({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="w-64 bg-surface-primary border border-border rounded p-2">
            <div className="text-xs text-muted px-2 pb-2">Project nav (preview)</div>
            {children}
        </div>
    )
}

/**
 * The variant comes from the `featureFlags` story parameter (handled by the global
 * decorator). This wrapper only stages the onboarding intent / override that the
 * logic reads from team-scoped localStorage, then mounts the logic so the entry resolves.
 */
function StoryRunner({ onboardingIntent, override, isCollapsed }: StoryArgs): JSX.Element | null {
    const [ready, setReady] = useState(false)

    useEffect(() => {
        window.localStorage.removeItem(PRODUCT_KEY)
        window.localStorage.removeItem(OVERRIDE_KEY)
        if (onboardingIntent) {
            window.localStorage.setItem(PRODUCT_KEY, onboardingIntent)
        }
        if (override) {
            window.localStorage.setItem(OVERRIDE_KEY, JSON.stringify(override))
        }

        const unmount = promotedProductLogic.mount()
        promotedProductLogic.actions.refreshIntentFromStorage()
        promotedProductLogic.actions.refreshOverrideFromStorage()
        setReady(true)

        return () => {
            window.localStorage.removeItem(PRODUCT_KEY)
            window.localStorage.removeItem(OVERRIDE_KEY)
            unmount()
            setReady(false)
        }
    }, [onboardingIntent, override])

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
        onboardingIntent: {
            control: { type: 'select' },
            options: [null, 'product_analytics', 'session_replay', 'web_analytics', 'error_tracking', 'llm_analytics'],
        },
        isCollapsed: { control: 'boolean' },
    },
    render: (args) => <StoryRunner {...args} />,
}
export default meta

type Story = StoryObj<StoryArgs>

export const ControlAHidden: Story = {
    args: { onboardingIntent: 'session_replay', override: null, isCollapsed: false },
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'control' } },
}

export const ControlBHidden: Story = {
    args: { onboardingIntent: 'session_replay', override: null, isCollapsed: false },
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'control_b' } },
}

export const IntentShowsOnboardingPick: Story = {
    args: { onboardingIntent: 'session_replay', override: null, isCollapsed: false },
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent' } },
}

export const IntentWithProductAnalytics: Story = {
    args: { onboardingIntent: 'product_analytics', override: null, isCollapsed: false },
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent' } },
}

export const IntentNoOnboardingPickHidden: Story = {
    args: { onboardingIntent: null, override: null, isCollapsed: false },
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent' } },
}

export const IntentPlusShowsCog: Story = {
    args: { onboardingIntent: 'session_replay', override: null, isCollapsed: false },
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent_plus' } },
}

export const IntentPlusWithUrlOverride: Story = {
    args: { onboardingIntent: 'session_replay', override: { kind: 'url', value: '/my-dashboard' }, isCollapsed: false },
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent_plus' } },
}

export const IntentCollapsedSidebar: Story = {
    args: { onboardingIntent: 'web_analytics', override: null, isCollapsed: true },
    parameters: { featureFlags: { [FEATURE_FLAGS.PROMOTED_PRODUCT]: 'intent' } },
}

export const FlagUnsetHidden: Story = {
    args: { onboardingIntent: 'session_replay', override: null, isCollapsed: false },
}
