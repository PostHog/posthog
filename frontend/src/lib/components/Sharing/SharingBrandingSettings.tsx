import { useActions, useValues } from 'kea'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonSwitch, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { backendAssetUrl } from 'lib/utils/apiHost'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature } from '~/types'

import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'
import { SharingLogicProps, sharingLogic } from './sharingLogic'

function isHttpUrl(value: string): boolean {
    try {
        const url = new URL(value)
        return url.protocol === 'http:' || url.protocol === 'https:'
    } catch {
        return false
    }
}

export interface SharingBrandingSettingsProps {
    logicProps: SharingLogicProps
}

export function SharingBrandingSettings({ logicProps }: SharingBrandingSettingsProps): JSX.Element {
    const { sharingSettings, sharingConfigurationLoading, whitelabelAvailable } = useValues(sharingLogic(logicProps))
    const { setSharingSettingsValue } = useActions(sharingLogic(logicProps))
    const { currentOrganization } = useValues(organizationLogic)
    const { showOrganizationLogo, brandLinkUrl, whitelabel } = sharingSettings
    const { showUpgradeModal } = useActions(upgradeModalLogic)
    const reduceMotion = useReducedMotion()
    const savingReason = sharingConfigurationLoading ? 'Saving…' : undefined
    const upgradeReason = whitelabelAvailable ? undefined : 'Available on Boost and higher plans'
    const logoMediaId = currentOrganization?.logo_media_id ?? null
    const logoSettingsUrl = urls.settings('organization-details', 'organization-display-name')

    const [linkDraft, setLinkDraft] = useState(brandLinkUrl ?? '')
    useEffect(() => {
        setLinkDraft(brandLinkUrl ?? '')
    }, [brandLinkUrl])

    const trimmedLink = linkDraft.trim()
    const linkError =
        trimmedLink && !isHttpUrl(trimmedLink) ? 'Enter a link that starts with http:// or https://' : undefined
    const saveLink = (): void => {
        const nextLink = trimmedLink || null
        if (!linkError && nextLink !== (brandLinkUrl ?? null)) {
            setSharingSettingsValue('brandLinkUrl', nextLink)
        }
    }

    return (
        <div className="col-span-2 rounded border p-3">
            <LemonSwitch
                fullWidth
                label="Show PostHog branding"
                checked={!whitelabel || !whitelabelAvailable}
                onChange={(checked) => setSharingSettingsValue('whitelabel', !checked)}
                disabledReason={upgradeReason || savingReason}
                loading={sharingConfigurationLoading}
                data-attr="sharing-branding-posthog"
            />
            {!whitelabelAvailable && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="text-xs text-secondary">
                        Remove PostHog branding and use your own logo with Boost.
                    </span>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => showUpgradeModal(AvailableFeature.WHITE_LABELLING)}
                        data-attr="sharing-branding-upgrade"
                    >
                        Upgrade to Boost
                    </LemonButton>
                </div>
            )}
            <AnimatePresence initial={false}>
                {whitelabelAvailable && whitelabel && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: reduceMotion ? 0 : 0.2, ease: 'easeInOut' }}
                        className="overflow-hidden"
                    >
                        <div className="pt-3">
                            <div className="border-t pt-3">
                                <div className="mb-3 text-sm font-semibold">Dashboard logo</div>
                                <LemonSwitch
                                    fullWidth
                                    label="Show organization logo"
                                    className="mb-3"
                                    checked={!!logoMediaId && showOrganizationLogo}
                                    onChange={(checked) => setSharingSettingsValue('showOrganizationLogo', checked)}
                                    disabledReason={
                                        savingReason ||
                                        (!logoMediaId ? 'Add a logo in organization settings first' : undefined)
                                    }
                                    loading={sharingConfigurationLoading}
                                    data-attr="sharing-show-organization-logo"
                                />
                                <div className="flex flex-wrap items-center gap-2">
                                    {logoMediaId && (
                                        <img
                                            className="max-h-10 max-w-40 rounded border object-contain p-1"
                                            src={backendAssetUrl(`/uploaded_media/${logoMediaId}`)}
                                            alt="Your organization logo"
                                        />
                                    )}
                                    <p className="mb-0 text-xs text-secondary">
                                        {logoMediaId ? 'Change your logo in ' : 'Add a logo in '}
                                        <Link to={logoSettingsUrl}>organization settings</Link>.
                                    </p>
                                </div>
                                <AnimatePresence initial={false}>
                                    {logoMediaId && showOrganizationLogo && (
                                        <motion.div
                                            initial={{ height: 0, opacity: 0 }}
                                            animate={{ height: 'auto', opacity: 1 }}
                                            exit={{ height: 0, opacity: 0 }}
                                            transition={{ duration: reduceMotion ? 0 : 0.2, ease: 'easeInOut' }}
                                            className="overflow-hidden"
                                        >
                                            <LemonField.Pure
                                                className="pt-3"
                                                label="Logo link"
                                                help="Where viewers go when they click your logo"
                                                error={linkError}
                                            >
                                                <LemonInput
                                                    value={linkDraft}
                                                    onChange={setLinkDraft}
                                                    onBlur={saveLink}
                                                    onPressEnter={saveLink}
                                                    placeholder="https://example.com"
                                                    size="small"
                                                    data-attr="sharing-brand-link-url"
                                                />
                                            </LemonField.Pure>
                                        </motion.div>
                                    )}
                                </AnimatePresence>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}
