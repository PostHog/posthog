import { LemonSearchableSelect, LemonSelectSection } from '@posthog/lemon-ui'

import { HeatmapVariantFilter, HeatmapVariantFlag } from 'lib/components/heatmaps/heatmapVariantFilter'

const optionKey = ({ flagKey, variant }: HeatmapVariantFilter): string => JSON.stringify([flagKey, variant])

export interface HeatmapVariantPickerProps {
    variantFilter: HeatmapVariantFilter | null
    variantFlags: HeatmapVariantFlag[]
    variantFilterGate: boolean
    onChange: (variantFilter: HeatmapVariantFilter | null) => void
    'data-attr': string
}

export function HeatmapVariantPicker({
    variantFilter,
    variantFlags,
    variantFilterGate,
    onChange,
    'data-attr': dataAttr,
}: HeatmapVariantPickerProps): JSX.Element | null {
    // A persisted filter stays visible so it can be cleared, even when its flag or the gate no longer loads.
    if (!variantFilter && (!variantFilterGate || !variantFlags.length)) {
        return null
    }

    const sections: LemonSelectSection<string | null>[] = variantFlags.map(({ flagKey, variants }) => ({
        title: flagKey,
        options: variants.map((option) => ({
            label: `${flagKey}: ${option.variant}`,
            labelInMenu: option.variant,
            value: optionKey(option),
        })),
    }))

    return (
        <LemonSearchableSelect
            size="small"
            dropdownMatchSelectWidth={false}
            data-attr={dataAttr}
            searchPlaceholder="Search flags or variants"
            searchInputDataAttr={`${dataAttr}-search`}
            // Fuse drops matches far into a string, so the variant gets its own key next to the long flag label.
            searchKeys={['label', 'labelInMenu']}
            tooltip="Heatmap: sessions that were shown this variant. Clickmap: clicks from people in this variant, even if they weren't shown it."
            value={variantFilter ? optionKey(variantFilter) : null}
            options={[{ options: [{ label: 'All variants', value: null }] }, ...sections]}
            renderButtonContent={() =>
                variantFilter ? `${variantFilter.flagKey}: ${variantFilter.variant}` : 'All variants'
            }
            onChange={(value) =>
                onChange(
                    variantFlags.flatMap(({ variants }) => variants).find((option) => optionKey(option) === value) ??
                        null
                )
            }
        />
    )
}
