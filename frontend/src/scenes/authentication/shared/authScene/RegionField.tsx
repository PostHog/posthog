import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonLabel, LemonModal, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

import { CLOUD_HOSTNAMES } from 'lib/constants'
import { countryCodeToFlag } from 'lib/utils/country'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

const REGION_SECTIONS = [
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

function RegionModal({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element {
    return (
        <LemonModal
            title="Which region would you like to choose?"
            description="It's possible to migrate to another region later."
            isOpen={open}
            onClose={onClose}
        >
            <ul className="list-none">
                {REGION_SECTIONS.map((section) => (
                    <li
                        key={section.title}
                        className="border-t first:border-t-0 border-dashed border-gray-accent mt-2 first:mt-0"
                    >
                        <h4 className="text-lg m-0 mt-2">{section.title}</h4>
                        <ul className="list-none p-0 my-2 deprecated-space-y-1">
                            {section.features.map((feature) => (
                                <li
                                    key={feature}
                                    className="flex items-center deprecated-space-x-2 text-gray-accent-light align-center"
                                >
                                    <IconCheckCircle className="w-[20px] flex-shrink-0" />
                                    <span className="text-black font-medium">{feature}</span>
                                </li>
                            ))}
                        </ul>
                    </li>
                ))}
            </ul>
        </LemonModal>
    )
}

const REGION_COUNTRY_CODE: Record<Region, string> = {
    [Region.US]: 'US',
    [Region.EU]: 'EU',
    [Region.DEV]: 'US',
}

function MiniFlag({ region }: { region: Region }): JSX.Element {
    return (
        <span className="shrink-0 leading-none" aria-hidden>
            {countryCodeToFlag(REGION_COUNTRY_CODE[region])}
        </span>
    )
}

const REGIONS: { value: Region; label: string }[] = [
    { value: Region.US, label: 'United States' },
    { value: Region.EU, label: 'European Union' },
]

export function RegionField(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const [devRegion, setDevRegion] = useState<Region>(Region.US)
    const [modalOpen, setModalOpen] = useState(false)

    if (!preflight?.cloud && !preflight?.is_debug) {
        return null
    }

    const activeRegion = preflight?.cloud ? (preflight.region ?? Region.US) : devRegion

    const selectRegion = (region: Region): void => {
        if (region === activeRegion) {
            return
        }
        if (preflight?.cloud) {
            const { pathname, search, hash } = router.values.currentLocation
            window.location.href = `https://${CLOUD_HOSTNAMES[region]}${pathname}${search}${hash}`
            return
        }
        setDevRegion(region)
    }

    const options: LemonSelectOptions<Region> = REGIONS.map((region) => ({
        value: region.value,
        label: (
            <span className="flex items-center gap-2">
                <MiniFlag region={region.value} />
                <span>{region.label}</span>
            </span>
        ),
    }))

    return (
        <>
            <RegionModal open={modalOpen} onClose={() => setModalOpen(false)} />
            <div className="flex flex-col gap-2">
                <LemonLabel onExplanationClick={() => setModalOpen(true)}>Data region</LemonLabel>
                <LemonSelect<Region>
                    value={activeRegion}
                    options={options}
                    fullWidth
                    onChange={(value) => value && selectRegion(value)}
                    renderButtonContent={(leaf) => {
                        const region = leaf?.value ?? activeRegion
                        return (
                            <span className="flex items-center gap-2">
                                <MiniFlag region={region} />
                                <span>{REGIONS.find((r) => r.value === region)?.label}</span>
                            </span>
                        )
                    }}
                />
            </div>
        </>
    )
}
