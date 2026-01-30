import './InsightOptions.scss'

import { router } from 'kea-router'
import { useState } from 'react'

import { IconPlay } from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'
import { INSIGHT_TYPE_URLS } from 'scenes/insights/utils'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

// Preview images/GIFs for each insight type
// Static images shown by default, GIFs play on hover
const INSIGHT_PREVIEWS: Partial<Record<InsightType, { static: string; animated: string }>> = {
    [InsightType.TRENDS]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/Screenshot_2026_01_26_at_19_04_42_402a468826.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/Screen_Recording_2026_01_26_at_19_03_59_32d2baa6cf.gif',
    },
    [InsightType.FUNNELS]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/Screenshot_2026_01_26_at_19_09_23_a8e1f25253.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/Screen_Recording_2026_01_26_at_19_09_11_a786c104da.gif',
    },
    [InsightType.RETENTION]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/Screenshot_2026_01_26_at_19_14_43_c69ffdca17.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/Screen_Recording_2026_01_26_at_19_14_50_72051492d0.gif',
    },
    [InsightType.PATHS]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/Screenshot_2026_01_26_at_19_22_42_100931dc71.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/Screen_Recording_2026_01_26_at_19_22_31_48a59903f2.gif',
    },
    [InsightType.STICKINESS]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/Screenshot_2026_01_26_at_19_26_36_752bac1184.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/Screen_Recording_2026_01_26_at_19_27_30_c45287c3a1.gif',
    },
    [InsightType.LIFECYCLE]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/Screenshot_2026_01_26_at_19_32_25_29e906f87a.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/Screen_Recording_2026_01_26_at_19_32_09_d05fabc1ec.gif',
    },
}

export const scene: SceneExport = {
    component: InsightOptions,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

interface InsightOptionCardProps {
    insightType: InsightType
    metadata: (typeof INSIGHT_TYPES_METADATA)[InsightType]
    index: number
}

function InsightOptionCard({ insightType, metadata, index }: InsightOptionCardProps): JSX.Element {
    const [isHovered, setIsHovered] = useState(false)
    const Icon = metadata.icon
    const url = INSIGHT_TYPE_URLS[insightType]
    const preview = INSIGHT_PREVIEWS[insightType]

    return (
        <div
            className="InsightOptions__card"
            style={{ animationDelay: `${index * 0.05}s` }}
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
            data-attr={`insight-option-${insightType.toLowerCase()}`}
        >
            <LemonCard
                className="cursor-pointer h-full overflow-hidden"
                hoverEffect
                onClick={() => router.actions.push(url)}
            >
                <div className="flex flex-col gap-3 h-full">
                    {preview && (
                        <div className="relative w-full aspect-video rounded overflow-hidden bg-fill-secondary">
                            <img
                                src={isHovered ? preview.animated : preview.static}
                                alt={`${metadata.name} preview`}
                                className="w-full h-full object-cover object-top transition-opacity duration-200"
                                loading="lazy"
                            />
                            <div
                                className={`absolute bottom-2 right-2 flex items-center gap-1 px-2 py-1 rounded-full bg-black/60 text-[10px] font-medium text-white transition-opacity duration-200 ${isHovered ? 'opacity-0' : 'opacity-100'}`}
                            >
                                <IconPlay className="w-3 h-3" />
                                <span>Hover to play</span>
                            </div>
                        </div>
                    )}
                    <div className="flex-1 flex flex-col gap-1">
                        <div className="flex items-center gap-2">
                            {Icon && <Icon className="text-lg text-secondary" />}
                            <div className="font-semibold text-default">{metadata.name}</div>
                        </div>
                        {metadata.description && (
                            <div className="text-sm text-secondary leading-snug">
                                {metadata.tooltipDescription || metadata.description}
                            </div>
                        )}
                    </div>
                    {metadata.tooltipDocLink && (
                        <Link
                            to={metadata.tooltipDocLink}
                            target="_blank"
                            className="text-xs mt-auto pt-2"
                            onClick={(e) => e.stopPropagation()}
                        >
                            Learn more
                        </Link>
                    )}
                </div>
            </LemonCard>
        </div>
    )
}

export function InsightOptions(): JSX.Element {
    const insightEntries = Object.entries(INSIGHT_TYPES_METADATA).filter(
        ([insightType, metadata]) =>
            metadata.inMenu &&
            insightType !== InsightType.JSON &&
            insightType !== InsightType.WEB_ANALYTICS &&
            insightType !== InsightType.HOG
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name="Create a new insight"
                description="Choose the type of insight that best fits your analysis needs"
                resourceType={{ type: 'product_analytics' }}
            />
            <div
                className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4 pb-16"
                data-attr="insight-options-page"
            >
                {insightEntries.map(([insightType, metadata], index) => (
                    <InsightOptionCard
                        key={insightType}
                        insightType={insightType as InsightType}
                        metadata={metadata}
                        index={index}
                    />
                ))}
            </div>
        </SceneContent>
    )
}
