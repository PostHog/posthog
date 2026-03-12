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
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/pasted_image_2026_03_10_T18_10_03_522_Z_ab651a8800.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/pasted_image_2026_03_10_T18_10_27_131_Z_0177e963f0.gif',
    },
    [InsightType.FUNNELS]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/pasted_image_2026_03_10_T18_14_07_880_Z_7ee2fb90ed.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/pasted_image_2026_03_10_T18_14_34_264_Z_3f0f703d98.gif',
    },
    [InsightType.RETENTION]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/pasted_image_2026_03_10_T18_20_00_462_Z_fabdd95b9e.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/pasted_image_2026_03_10_T18_20_19_530_Z_c6f565345c.gif',
    },
    [InsightType.PATHS]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/pasted_image_2026_03_10_T18_23_20_097_Z_30f1fda15b.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/pasted_image_2026_03_10_T18_23_22_284_Z_752ff95327.gif',
    },
    [InsightType.STICKINESS]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/pasted_image_2026_03_10_T18_25_59_328_Z_531c3fd175.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/pasted_image_2026_03_10_T18_26_03_428_Z_fc19cf49aa.gif',
    },
    [InsightType.LIFECYCLE]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/pasted_image_2026_03_10_T18_27_42_832_Z_c0b26ea9c3.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/pasted_image_2026_03_10_T18_27_44_710_Z_57de365180.gif',
    },
    [InsightType.SQL]: {
        static: 'https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/pasted_image_2026_03_10_T18_30_00_396_Z_133afc4f54.png',
        animated:
            'https://res.cloudinary.com/dmukukwp6/image/upload/pasted_image_2026_03_10_T18_30_06_034_Z_56a680a474.gif',
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
        >
            <LemonCard
                className="cursor-pointer h-full overflow-hidden"
                data-attr={`insight-option-${insightType.toLowerCase()}`}
                hoverEffect
                onClick={() => router.actions.push(url)}
            >
                <div className="flex flex-col gap-3 h-full">
                    {preview && (
                        <div className="relative w-full aspect-video overflow-hidden bg-fill-secondary">
                            <img
                                src={isHovered ? preview.animated : preview.static}
                                alt={`${metadata.name} preview`}
                                className="w-full h-full object-contain object-top transition-opacity duration-200"
                                loading="lazy"
                            />
                            <div
                                className={`absolute top-2 left-2 flex items-center gap-1 px-2 py-1 rounded-full bg-black/60 text-[10px] font-medium text-white transition-opacity duration-200 ${isHovered ? 'opacity-0' : 'opacity-100'}`}
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
