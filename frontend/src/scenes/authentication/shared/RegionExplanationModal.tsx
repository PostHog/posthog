import { IconCheckCircle } from '@posthog/icons'
import { LemonModal } from '@posthog/lemon-ui'

import { Region } from '~/types'

const REGION_SECTIONS: { region: Region; title: string; features: string[] }[] = [
    {
        region: Region.US,
        title: 'US hosting',
        features: [
            'Faster if you and your users are based in the US',
            'Easier to comply with some US regulations',
            'Hosted in Virginia, USA',
        ],
    },
    {
        region: Region.EU,
        title: 'EU hosting',
        features: [
            'Faster if you and your users are based in Europe',
            'Keeps data in the EU to comply with GDPR requirements',
            'Hosted in Frankfurt, Germany',
        ],
    },
]

export function RegionExplanationModal({
    open,
    onClose,
    onSelectRegion,
}: {
    open: boolean
    onClose: () => void
    onSelectRegion: (region: Region) => void
}): JSX.Element {
    return (
        <LemonModal
            title="Which region would you like to choose?"
            description="It's possible to migrate to another region later."
            isOpen={open}
            onClose={onClose}
        >
            <ul className="list-none p-0 m-0 deprecated-space-y-2">
                {REGION_SECTIONS.map((section) => (
                    <li key={section.title}>
                        <button
                            type="button"
                            onClick={() => {
                                onSelectRegion(section.region)
                                onClose()
                            }}
                            className="flex w-full flex-col items-start gap-1 rounded border border-primary px-3 py-2 text-left transition-colors hover:border-accent"
                        >
                            <h4 className="text-lg m-0">{section.title}</h4>
                            <ul className="list-none p-0 m-0 deprecated-space-y-1">
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
                        </button>
                    </li>
                ))}
            </ul>
        </LemonModal>
    )
}
