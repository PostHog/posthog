import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonModal, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { CLOUD_HOSTNAMES } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { oauthLogic } from 'lib/oauth/oauthLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

const sections = [
    {
        title: 'US hosting',
        features: [
            'Faster if you and your users are based in the US',
            'Easier to comply with some US regulations',
            'Hosted in Virginia, USA',
        ],
    },
    {
        title: 'EU hosting',
        features: [
            'Faster if you and your users are based in Europe',
            'Keeps data in the EU to comply with GDPR requirements',
            'Hosted in Frankfurt, Germany',
        ],
    },
]

function WhyCloudModal({ setOpen, open }: { setOpen: (open: boolean) => void; open: boolean }): JSX.Element {
    return (
        <LemonModal
            title="Which region would you like to choose?"
            description="It's possible to migrate to another region later."
            isOpen={open}
            onClose={() => setOpen(false)}
        >
            <ul className="list-none">
                {sections.map((section) => {
                    return (
                        <li
                            key={section.title}
                            className="border-t first:border-t-0 border-dashed border-gray-accent mt-2 first:mt-0"
                        >
                            <h4 className="text-lg m-0 mt-2">{section.title}</h4>
                            <ul className="list-none p-0 my-2 deprecated-space-y-1">
                                {section.features.map((feature) => {
                                    return (
                                        <li
                                            key={feature}
                                            className="flex items-center deprecated-space-x-2 text-gray-accent-light align-center"
                                        >
                                            <IconCheckCircle className="w-[20px] flex-shrink-0" />
                                            <span className="text-black font-medium">{feature}</span>
                                        </li>
                                    )
                                })}
                            </ul>
                        </li>
                    )
                })}
            </ul>
        </LemonModal>
    )
}

export default function RegionSelect(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { loginInProgress } = useValues(oauthLogic)
    const { beginLogin } = useActions(oauthLogic)
    const [regionModalOpen, setRegionModalOpen] = useState(false)

    // Local dev: offer signing into a remote cloud region over OAuth, styled like the PostHog Code
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

    return (
        <>
            <LemonField.Pure label="Data region" onExplanationClick={() => setRegionModalOpen(true)}>
                <LemonSelect
                    onChange={(region) => {
                        if (!region) {
                            return
                        }
                        const { pathname, search, hash } = router.values.currentLocation
                        const newUrl = `https://${CLOUD_HOSTNAMES[region]}${pathname}${search}${hash}`
                        window.location.href = newUrl
                    }}
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

            <WhyCloudModal open={regionModalOpen} setOpen={setRegionModalOpen} />
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
