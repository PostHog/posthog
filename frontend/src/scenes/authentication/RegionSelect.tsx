import { IconCheckCircle } from '@posthog/icons'
import { LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { CLOUD_HOSTNAMES, FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useState } from 'react'
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
        <LemonModal title="Which region would you like to choose?" isOpen={open} onClose={() => setOpen(false)}>
            <div className="bg-bg-light w-full max-w-248 h-full ml-auto relative z-10 overflow-auto">
                <h3 className="text-lg text-semibold opacity-50 m-0">
                    A particular region can have advantages, but you can migrate regions at any time for free.
                </h3>
                <ul className="list-none m-0 p-0 mt-6">
                    {sections.map((section) => {
                        return (
                            <li
                                key={section.title}
                                className="border-t first:border-t-0 border-dashed border-gray-accent mt-4 pt-2 first:mt-0"
                            >
                                <h4 className="text-lg m-0 mt-4">{section.title}</h4>
                                <ul className="list-none p-0 my-2 space-y-1">
                                    {section.features.map((feature) => {
                                        return (
                                            <li
                                                key={feature}
                                                className="flex items-center space-x-2 text-gray-accent-light align-center"
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
            </div>
        </LemonModal>
    )
}

const RegionSelect = (): JSX.Element | null => {
    const { preflight } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [regionModalOpen, setRegionModalOpen] = useState(false)
    if (!featureFlags[FEATURE_FLAGS.REGION_SELECT] || !preflight?.cloud || !preflight?.region) {
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
