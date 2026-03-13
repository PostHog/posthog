import { connect, kea, path, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import type { membersPlatformAddonAdLogicType } from './membersPlatformAddonAdLogicType'

export type MembersPagePlatformAddonAdKey =
    | 'test-audit-trail'
    | 'test-paper-trail'
    | 'test-space-scale'
    | 'test-big-village'

const platformAddonAdVariants: Record<
    MembersPagePlatformAddonAdKey,
    {
        title: string
        description: string
        cta: string
        alt: string
    }
> = {
    'test-audit-trail': {
        title: 'Who keeps changing these f***ing settings?!?',
        description: 'Upgrade for advanced member permissions and audit logs of who did what and when.',
        cta: 'Upgrade now',
        alt: 'Detective hedgehog inspecting...stuff',
    },
    'test-paper-trail': {
        title: "I'm so tired of granting people permissions to things. What about you?",
        description:
            'Give admins more control over member permissions and keep audit logs for every important action with a platform add-on.',
        cta: 'Upgrade for more control',
        alt: 'Judge hedgehog holding a gavel',
    },
    'test-space-scale': {
        title: 'What if Neil Hogstrong deleted the rover on the way to the moon?',
        description: 'With a platform add-on, get advanced member permissions plus audit logs for every action.',
        cta: 'Wow sounds really cool tell me more',
        alt: 'Space hedgehog floating with a visor',
    },
    'test-big-village': {
        title: 'Village got too many villagers to look after?',
        description: 'Upgrade for more control over member permissions plus audit logs for every action.',
        cta: 'Upgrade now',
        alt: 'Hedgehogs eating porridge',
    },
}

export const membersPlatformAddonAdLogic = kea<membersPlatformAddonAdLogicType>([
    path(['scenes', 'settings', 'organization', 'membersPlatformAddonAdLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], userLogic, ['hasAvailableFeature']],
    })),
    selectors({
        platformAddonAdVariant: [
            (s) => [s.featureFlags],
            (featureFlags): boolean | string | undefined => featureFlags[FEATURE_FLAGS.MEMBERS_PAGE_PLATFORM_ADDON_AD],
        ],
        hasAccessToAdvertisedFeatures: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature): boolean =>
                hasAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS) ||
                hasAvailableFeature(AvailableFeature.AUDIT_LOGS),
        ],
        platformAddonAdKey: [
            (s) => [s.platformAddonAdVariant],
            (variant): MembersPagePlatformAddonAdKey =>
                typeof variant === 'string' && variant in platformAddonAdVariants
                    ? (variant as MembersPagePlatformAddonAdKey)
                    : 'test-audit-trail',
        ],
        platformAddonAdConfig: [
            (s) => [s.platformAddonAdKey],
            (
                key
            ): {
                key: MembersPagePlatformAddonAdKey
                title: string
                description: string
                cta: string
                alt: string
            } => ({ key, ...platformAddonAdVariants[key] }),
        ],
        shouldShowPlatformAddonAd: [
            (s) => [s.platformAddonAdVariant, s.hasAccessToAdvertisedFeatures],
            (variant, hasAccessToAdvertisedFeatures): boolean =>
                !!variant && variant !== 'control' && !hasAccessToAdvertisedFeatures,
        ],
    }),
])
