import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSelect, LemonSelectSection } from '@posthog/lemon-ui'

import { HeatmapVariantFilter } from 'lib/components/heatmaps/heatmapVariantFilter'
import { FEATURE_FLAGS } from 'lib/constants'

import { heatmapToolbarMenuLogic } from '~/toolbar/shared/elements/heatmapToolbarMenuLogic'
import { flagsToolbarLogic } from '~/toolbar/shared/flags/flagsToolbarLogic'
import { useToolbarFeatureFlag } from '~/toolbar/shared/toolbarPosthogJS'

const optionKey = ({ flagKey, variant }: HeatmapVariantFilter): string => JSON.stringify([flagKey, variant])

export function HeatmapVariantPicker(): JSX.Element | null {
    const eventFilterEnabled = useToolbarFeatureFlag(FEATURE_FLAGS.HEATMAPS_EVENT_FILTER)
    const { heatmapVariantFilter, heatmapVariantFlags } = useValues(heatmapToolbarMenuLogic)
    const { setHeatmapVariantFilter } = useActions(heatmapToolbarMenuLogic)
    const { getUserFlags } = useActions(flagsToolbarLogic)

    useEffect(() => {
        if (eventFilterEnabled) {
            getUserFlags()
        }
    }, [eventFilterEnabled, getUserFlags])

    // A persisted filter stays visible so it can be cleared, even when its flag or the gate no longer loads.
    if (!heatmapVariantFilter && (!eventFilterEnabled || !heatmapVariantFlags.length)) {
        return null
    }

    const sections: LemonSelectSection<string | null>[] = heatmapVariantFlags.map(({ flagKey, variants }) => ({
        title: flagKey,
        options: variants.map((variantFilter) => ({ label: variantFilter.variant, value: optionKey(variantFilter) })),
    }))

    return (
        <LemonSelect
            size="small"
            dropdownMatchSelectWidth={false}
            data-attr="heatmap-variant-filter"
            value={heatmapVariantFilter ? optionKey(heatmapVariantFilter) : null}
            options={[{ options: [{ label: 'All variants', value: null }] }, ...sections]}
            renderButtonContent={() =>
                heatmapVariantFilter
                    ? `${heatmapVariantFilter.flagKey}: ${heatmapVariantFilter.variant}`
                    : 'All variants'
            }
            onChange={(value) =>
                setHeatmapVariantFilter(
                    heatmapVariantFlags
                        .flatMap(({ variants }) => variants)
                        .find((variantFilter) => optionKey(variantFilter) === value) ?? null
                )
            }
        />
    )
}
