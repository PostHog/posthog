import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { DetectiveHog, JudgeHog, SpaceHog, ThreeBearsHogs } from 'lib/components/hedgehogs'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { membersPlatformAddonAdLogic } from 'scenes/settings/organization/membersPlatformAddonAdLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { MembersPagePlatformAddonAdKey } from './membersPlatformAddonAdLogic'

const platformAddonAdIllustrations: Record<MembersPagePlatformAddonAdKey, typeof DetectiveHog> = {
    'test-audit-trail': DetectiveHog,
    'test-paper-trail': JudgeHog,
    'test-space-scale': SpaceHog,
    'test-big-village': ThreeBearsHogs,
}

const dismissKey = 'organization-members-platform-addon-ad'

export function MembersPlatformAddonAd(): JSX.Element | null {
    const bannerLogic = lemonBannerLogic({ dismissKey })
    const { shouldShowPlatformAddonAd, platformAddonAdConfig } = useValues(membersPlatformAddonAdLogic)
    const { isDismissed } = useValues(bannerLogic)
    const { dismiss } = useActions(bannerLogic)

    if (!shouldShowPlatformAddonAd || isDismissed) {
        return null
    }

    const PlatformAddonAdIllustration = platformAddonAdIllustrations[platformAddonAdConfig.key]

    return (
        <LemonBanner type="info" hideIcon>
            <div className="flex flex-row gap-8 px-8 items-center justify-evenly">
                <div>
                    <h3 className="mb-1 text-lg font-semibold">{platformAddonAdConfig.title}</h3>
                    <p className="mb-3">{platformAddonAdConfig.description}</p>
                    <div className="flex flex-row gap-2">
                        <LemonButton
                            type="primary"
                            className="w-fit"
                            to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}
                        >
                            {platformAddonAdConfig.cta}
                        </LemonButton>
                        <LemonButton type="tertiary" onClick={() => dismiss()}>
                            I'm not interested
                        </LemonButton>
                    </div>
                </div>
                <PlatformAddonAdIllustration
                    className={clsx('h-52 w-fit', platformAddonAdConfig.key === 'test-paper-trail' && 'p-4')}
                    alt={platformAddonAdConfig.alt}
                />
            </div>
        </LemonBanner>
    )
}
