import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { LemonLabel, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

import { CLOUD_HOSTNAMES } from 'lib/constants'
import { countryCodeToFlag } from 'lib/utils/country'
import { RegionExplanationModal } from 'scenes/authentication/shared/RegionExplanationModal'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

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
            <RegionExplanationModal
                open={modalOpen}
                onClose={() => setModalOpen(false)}
                onSelectRegion={selectRegion}
            />
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
