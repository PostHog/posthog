import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { CLOUD_HOSTNAMES } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
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
                            className="border-gray-accent mt-2 border-t border-dashed first:mt-0 first:border-t-0"
                        >
                            <h4 className="m-0 mt-2 text-lg">{section.title}</h4>
                            <ul className="deprecated-space-y-1 my-2 list-none p-0">
                                {section.features.map((feature) => {
                                    return (
                                        <li
                                            key={feature}
                                            className="deprecated-space-x-2 text-gray-accent-light align-center flex items-center"
                                        >
                                            <IconCheckCircle className="w-[20px] flex-shrink-0" />
                                            <span className="font-medium text-black">{feature}</span>
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

const RegionSelect = (): JSX.Element | null => {
    const { preflight } = useValues(preflightLogic)
    const [regionModalOpen, setRegionModalOpen] = useState(false)

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

export default RegionSelect
