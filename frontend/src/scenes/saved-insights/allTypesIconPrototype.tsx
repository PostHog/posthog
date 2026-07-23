/**
 * PROTOTYPE — throwaway, do not ship.
 *
 * Question: which icon should the "All types" option of the insight type filter use?
 * Plan: five variants (A = current, no icon; B–E = icon candidates) on the existing
 * saved-insights route, switchable via `?variant=` or the floating bottom bar (←/→ too).
 *
 * savedInsightsLogic rewrites the URL with filter params only, dropping `?variant=` —
 * so the current variant also lives in component state + localStorage to survive that.
 *
 * Once an icon wins: set it on the 'All types' entry of INSIGHT_TYPE_OPTIONS in
 * insightTypesMetadata.tsx, then delete this file and its uses in SavedInsightsFilters.
 */
import { useEffect, useState } from 'react'

import { router } from 'kea-router'

import { IconApps, IconAsterisk, IconChevronLeft, IconChevronRight, IconGridMasonry, IconStack } from '@posthog/icons'

import { LemonSelectOption, LemonSelectOptions } from '@posthog/lemon-ui'

interface AllTypesIconVariant {
    key: string
    name: string
    icon: JSX.Element | null
}

export const ALL_TYPES_ICON_VARIANTS: AllTypesIconVariant[] = [
    { key: 'A', name: 'Current (no icon)', icon: null },
    { key: 'B', name: 'Asterisk (wildcard)', icon: <IconAsterisk /> },
    { key: 'C', name: 'Stack (layers)', icon: <IconStack /> },
    { key: 'D', name: 'Masonry (mosaic of charts)', icon: <IconGridMasonry /> },
    { key: 'E', name: 'Apps (grid of types)', icon: <IconApps /> },
]

const STORAGE_KEY = 'ph-prototype-all-types-icon-variant'

function normalizeVariant(key: string | null | undefined): string {
    return ALL_TYPES_ICON_VARIANTS.some((v) => v.key === key) ? (key as string) : 'A'
}

export function useAllTypesIconVariant(): [string, (direction: 1 | -1) => void] {
    const [variant, setVariant] = useState(() =>
        normalizeVariant(router.values.searchParams.variant ?? localStorage.getItem(STORAGE_KEY))
    )

    const cycle = (direction: 1 | -1): void => {
        const index = ALL_TYPES_ICON_VARIANTS.findIndex((v) => v.key === variant)
        const nextIndex = (index + direction + ALL_TYPES_ICON_VARIANTS.length) % ALL_TYPES_ICON_VARIANTS.length
        const next = ALL_TYPES_ICON_VARIANTS[nextIndex].key
        setVariant(next)
        localStorage.setItem(STORAGE_KEY, next)
        const { location, searchParams, hashParams } = router.values
        router.actions.replace(location.pathname, { ...searchParams, variant: next }, hashParams)
    }

    return [variant, cycle]
}

/** Swap the icon on the 'All types' entry according to the active variant. */
export function withAllTypesIconVariant(
    options: LemonSelectOptions<string>,
    variantKey: string
): LemonSelectOptions<string> {
    const icon = ALL_TYPES_ICON_VARIANTS.find((v) => v.key === variantKey)?.icon
    if (!icon) {
        return options
    }
    return (options as LemonSelectOption<string>[]).map((option) =>
        'value' in option && option.value === 'All types' ? { ...option, icon } : option
    )
}

export function AllTypesIconPrototypeSwitcher({
    variant,
    onCycle,
}: {
    variant: string
    onCycle: (direction: 1 | -1) => void
}): JSX.Element | null {
    useEffect(() => {
        if (process.env.NODE_ENV === 'production') {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            const target = event.target as HTMLElement | null
            if (target?.closest('input, textarea, [contenteditable="true"]')) {
                return
            }
            if (event.key === 'ArrowLeft') {
                onCycle(-1)
            } else if (event.key === 'ArrowRight') {
                onCycle(1)
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    })

    if (process.env.NODE_ENV === 'production') {
        return null
    }

    const active = ALL_TYPES_ICON_VARIANTS.find((v) => v.key === variant) ?? ALL_TYPES_ICON_VARIANTS[0]

    return (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[9999] flex items-center gap-2 rounded-full bg-black text-white px-3 py-1.5 shadow-lg text-sm select-none">
            <button
                type="button"
                className="flex items-center p-1 rounded-full hover:bg-white/20 cursor-pointer"
                onClick={() => onCycle(-1)}
                aria-label="Previous variant"
            >
                <IconChevronLeft />
            </button>
            <span className="flex items-center gap-1.5 whitespace-nowrap font-medium">
                {active.icon}
                {active.key} — {active.name}
            </span>
            <button
                type="button"
                className="flex items-center p-1 rounded-full hover:bg-white/20 cursor-pointer"
                onClick={() => onCycle(1)}
                aria-label="Next variant"
            >
                <IconChevronRight />
            </button>
        </div>
    )
}
