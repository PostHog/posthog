import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { CLOUD_HOSTNAMES } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { oauthLogic } from 'lib/oauth/oauthLogic'
import { RegionExplanationModal } from 'scenes/authentication/shared/RegionExplanationModal'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

export default function RegionSelect(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { loginInProgress } = useValues(oauthLogic)
    const { beginLogin } = useActions(oauthLogic)
    const [regionModalOpen, setRegionModalOpen] = useState(false)

    // Local dev: offer signing into a remote cloud region over OAuth, styled like the PostHog Desktop
    // desktop region picker. Keeping "Local" uses the usual session-cookie form below; picking
    // US/EU kicks off the OAuth flow against that region.
    if (preflight?.is_debug) {
        return (
            <div className="flex flex-col gap-2">
                <div className="grid grid-cols-2 gap-2">
                    <RegionCard
                        flag="🇺🇸"
                        label="US Cloud"
                        hint="us.posthog.com"
                        isOAuth
                        disabled={loginInProgress}
                        onClick={() => beginLogin(Region.US)}
                    />
                    <RegionCard
                        flag="🇪🇺"
                        label="EU Cloud"
                        hint="eu.posthog.com"
                        isOAuth
                        disabled={loginInProgress}
                        onClick={() => beginLogin(Region.EU)}
                    />
                </div>
                <RegionCard flag="💻" label="Local (this instance)" hint="Log in with the form below" selected />
            </div>
        )
    }

    if (!preflight?.cloud || !preflight?.region) {
        return null
    }

    const selectRegion = (region: Region): void => {
        const { pathname, search, hash } = router.values.currentLocation
        window.location.href = `https://${CLOUD_HOSTNAMES[region]}${pathname}${search}${hash}`
    }

    return (
        <>
            <LemonField.Pure label="Data region" onExplanationClick={() => setRegionModalOpen(true)}>
                <LemonSelect
                    onChange={(region) => region && selectRegion(region)}
                    value={preflight?.region}
                    options={[
                        {
                            label: 'United States',
                            value: Region.US,
                        },
                        {
                            label: 'European Union',
                            value: Region.EU,
                        },
                    ]}
                    fullWidth
                />
            </LemonField.Pure>

            <RegionExplanationModal
                open={regionModalOpen}
                onClose={() => setRegionModalOpen(false)}
                onSelectRegion={selectRegion}
            />
        </>
    )
}

function RegionCard({
    flag,
    label,
    hint,
    isOAuth,
    selected = false,
    disabled = false,
    onClick,
}: {
    flag: string
    label: string
    hint: string
    isOAuth?: boolean
    selected?: boolean
    disabled?: boolean
    onClick?: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            aria-pressed={selected}
            onClick={onClick}
            disabled={disabled || selected}
            className={clsx(
                'flex w-full flex-col items-start gap-0.5 rounded border px-3 py-2 text-left transition-colors',
                selected ? 'border-accent bg-accent-highlight' : 'border-primary hover:border-accent',
                disabled && !selected ? 'cursor-not-allowed opacity-60' : !selected && 'cursor-pointer'
            )}
        >
            <div className="flex w-full items-center gap-2">
                <span className="text-lg leading-none">{flag}</span>
                <span className="text-sm font-semibold">{label}</span>
                {isOAuth && (
                    <LemonTag type="primary" size="small" className="ml-auto">
                        OAuth
                    </LemonTag>
                )}
            </div>
            <span className="pl-6.75 text-xs text-secondary">{hint}</span>
        </button>
    )
}
