import { useValues } from 'kea'

import { IconCheck } from '@posthog/icons'

import { IconBlank } from 'lib/lemon-ui/icons'
import { LemonMenuSection } from 'lib/lemon-ui/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { fileSystemTypes } from '~/products'
import { FileSystemType } from '~/types'

const missingProductTypes: { value: string; label: string; flag?: string }[] = [
    { value: 'destination', label: 'Destinations' },
    { value: 'site_app', label: 'Web scripts' },
    { value: 'source', label: 'Sources' },
    { value: 'transformation', label: 'Transformations' },
]
// TODO: This is a duplicate of TreeSearchField.tsx
const productTypesMapped = [
    ...Object.entries(fileSystemTypes as unknown as Record<string, FileSystemType>).map(
        ([key, value]): { value: string; label: string; flag?: string } => ({
            value: value.filterKey || key,
            label: value.name,
            flag: value.flag,
        })
    ),
    ...missingProductTypes,
]

export function useTreeFilterMenuItems(searchTerm: string, setSearchTerm: (term: string) => void): LemonMenuSection[] {
    const { featureFlags } = useValues(featureFlagLogic)
    const tags = searchTerm.split(' ')
    const onlyMine = tags.includes('user:me')

    return [
        {
            items: [
                {
                    label: 'Only my stuff',
                    icon: onlyMine ? <IconCheck /> : <IconBlank />,
                    active: onlyMine,
                    'data-attr': 'tree-filters-dropdown-menu-only-my-stuff-button',
                    onClick: () =>
                        setSearchTerm(
                            onlyMine
                                ? tags
                                      .filter((tag) => tag !== 'user:me')
                                      .join(' ')
                                      .trim()
                                : `${searchTerm.trim()} user:me`.trim()
                        ),
                },
            ],
        },
        {
            items: productTypesMapped
                .filter(
                    (productType) => !productType.flag || featureFlags[productType.flag as keyof typeof featureFlags]
                )
                .map((productType) => {
                    const active = tags.includes(`type:${productType.value}`)
                    const withoutType = tags
                        .filter((tag) => !tag.startsWith('type:'))
                        .join(' ')
                        .trim()
                    return {
                        label: productType.label,
                        icon: active ? <IconCheck /> : <IconBlank />,
                        active,
                        'data-attr': `tree-filters-dropdown-menu-${productType.value}-button`,
                        onClick: () =>
                            setSearchTerm(active ? withoutType : `${withoutType} type:${productType.value}`.trim()),
                    }
                }),
        },
    ]
}
