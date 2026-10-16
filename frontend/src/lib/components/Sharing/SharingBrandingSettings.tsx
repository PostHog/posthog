import { useActions, useValues } from 'kea'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { backendAssetUrl } from 'lib/utils/apiHost'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature } from '~/types'

import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'
import { SharingLogicProps, sharingLogic } from './sharingLogic'

export interface SharingBrandingSettingsProps {
    logicProps: SharingLogicProps
}

export function SharingBrandingSettings({ logicProps }: SharingBrandingSettingsProps): JSX.Element {
    const { sharingSettings, settingsBeingSaved, whitelabelAvailable } = useValues(sharingLogic(logicProps))
    const { setDashboardBranding } = useActions(sharingLogic(logicProps))
    const { currentOrganization } = useValues(organizationLogic)
    const { showOrganizationLogo, whitelabel } = sharingSettings
    const { showUpgradeModal } = useActions(upgradeModalLogic)
    const logoMediaId = currentOrganization?.logo_media_id ?? null
    const logoSettingsUrl = urls.settings('organization-details', 'organization-display-name')
    let posthogDisabledReason: string | undefined
    let logoDisabledReason: string | undefined
    if (!whitelabelAvailable) {
        posthogDisabledReason = 'Remove PostHog branding on Boost and higher plans'
    } else {
        if (settingsBeingSaved.showOrganizationLogo) {
            posthogDisabledReason = 'Saving branding'
        }
        if (settingsBeingSaved.whitelabel) {
            logoDisabledReason = 'Saving branding'
        }
    }
    const upgradeLogoButton = !whitelabelAvailable && (
        <LemonButton
            size="small"
            type="tertiary"
            icon={<IconLock />}
            tooltip="Show your organization logo on shared dashboards with Boost or a higher plan."
            onClick={() => showUpgradeModal(AvailableFeature.WHITE_LABELLING)}
            aria-label="Upgrade to Boost to show your logo"
        />
    )

    return (
        <div className="col-span-2 rounded border p-3">
            <div className="flex items-center justify-between gap-2 px-2">
                <div className="flex items-center gap-1.5">
                    <label htmlFor="sharing-branding-posthog-switch" className="font-medium">
                        Show PostHog branding
                    </label>
                </div>
                <LemonSwitch
                    id="sharing-branding-posthog-switch"
                    aria-label="Show PostHog branding"
                    checked={!whitelabel || !whitelabelAvailable}
                    onChange={(checked) =>
                        setDashboardBranding({
                            whitelabel: !checked,
                            showOrganizationLogo: false,
                            setting: 'whitelabel',
                        })
                    }
                    disabledReason={posthogDisabledReason}
                    loading={settingsBeingSaved.whitelabel}
                    data-attr="sharing-branding-posthog"
                />
            </div>
            <div className="mt-3 border-t pt-3">
                {logoMediaId ? (
                    <>
                        <div className="flex items-center justify-between gap-2 px-2">
                            <span className="font-medium">Show organization logo</span>
                            {whitelabelAvailable ? (
                                <LemonSwitch
                                    id="sharing-organization-logo-switch"
                                    aria-label="Show organization logo"
                                    checked={whitelabel && showOrganizationLogo}
                                    onChange={(checked) =>
                                        setDashboardBranding({
                                            whitelabel: true,
                                            showOrganizationLogo: checked,
                                            setting: 'showOrganizationLogo',
                                        })
                                    }
                                    disabledReason={logoDisabledReason}
                                    loading={settingsBeingSaved.showOrganizationLogo}
                                    data-attr="sharing-show-organization-logo"
                                />
                            ) : (
                                upgradeLogoButton
                            )}
                        </div>
                        {whitelabelAvailable && (
                            <div className="mt-3 flex flex-wrap items-center gap-2 px-2">
                                <img
                                    className="max-h-10 max-w-40 rounded border object-contain p-1"
                                    src={backendAssetUrl(`/uploaded_media/${logoMediaId}`)}
                                    alt="Your organization logo"
                                />
                                <p className="mb-0 text-xs text-secondary">
                                    <Link to={logoSettingsUrl} target="_blank">
                                        Change your logo here
                                    </Link>
                                </p>
                            </div>
                        )}
                    </>
                ) : (
                    <div className="flex flex-wrap items-center justify-between gap-3 px-2">
                        <div>
                            <div className="flex items-center gap-1.5 font-medium">
                                <span>Show your organization logo</span>
                            </div>
                        </div>
                        {whitelabelAvailable ? (
                            <LemonButton type="secondary" size="small" to={logoSettingsUrl} targetBlank>
                                Add your logo
                            </LemonButton>
                        ) : (
                            upgradeLogoButton
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
