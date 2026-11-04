import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSelectSection } from '@posthog/lemon-ui'

import { HeatmapVariantFilter as VariantFilter } from 'lib/components/heatmaps/heatmapVariantFilter'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { heatmapToolbarMenuLogic } from '~/toolbar/shared/elements/heatmapToolbarMenuLogic'
import { flagsToolbarLogic } from '~/toolbar/shared/flags/flagsToolbarLogic'
import { toolbarPosthogJS } from '~/toolbar/shared/toolbarPosthogJS'

const optionKey = ({ flagKey, variant }: VariantFilter): string => JSON.stringify([flagKey, variant])

export function HeatmapVariantFilter(): JSX.Element | null {
    const { userFlags } = useValues(flagsToolbarLogic)
    const { getUserFlags } = useActions(flagsToolbarLogic)
    const { heatmapVariantFilter } = useValues(heatmapToolbarMenuLogic)
    const { setHeatmapVariantFilter } = useActions(heatmapToolbarMenuLogic)

    useOnMountEffect(getUserFlags)

    const variantsByKey = new Map<string, VariantFilter>()
    const sections: LemonSelectSection<string | null>[] = userFlags
        .filter(({ feature_flag }) => feature_flag.filters?.multivariate?.variants?.length)
        .map(({ feature_flag }) => ({
            title: feature_flag.key,
            options: (feature_flag.filters.multivariate?.variants ?? []).map(({ key: variant }) => {
                const variantFilter = { flagKey: feature_flag.key, variant }
                variantsByKey.set(optionKey(variantFilter), variantFilter)
                return { label: variant, value: optionKey(variantFilter) }
            }),
        }))

    // A persisted filter stays visible so it can be cleared, even when its flag no longer loads.
    if (
        !heatmapVariantFilter &&
        (!sections.length || !toolbarPosthogJS.getFeatureFlag(FEATURE_FLAGS.HEATMAPS_EVENT_FILTER))
    ) {
        return null
    }

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
            onChange={(value) => setHeatmapVariantFilter(value ? (variantsByKey.get(value) ?? null) : null)}
        />
    )
}
