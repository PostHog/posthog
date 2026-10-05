import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'

import { IconBlank } from 'lib/lemon-ui/icons'
import { LemonMenuSection } from 'lib/lemon-ui/LemonMenu'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { fileSystemTypes } from '~/products'
import { FileSystemType } from '~/types'

import { ProjectTreeLogicProps, projectTreeLogic } from './projectTreeLogic'

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

export function useTreeFilterMenuItems(logicProps: ProjectTreeLogicProps): LemonMenuSection[] {
    const { featureFlags } = useValues(featureFlagLogic)
    const { searchFilters } = useValues(projectTreeLogic(logicProps))
    const { toggleOnlyMyStuff, toggleFileTypeFilter } = useActions(projectTreeLogic(logicProps))

    return [
        {
            items: [
                {
                    label: 'Only my stuff',
                    icon: searchFilters.onlyMine ? <IconCheck /> : <IconBlank />,
                    active: searchFilters.onlyMine,
                    'data-attr': 'tree-filters-dropdown-menu-only-my-stuff-button',
                    onClick: toggleOnlyMyStuff,
                },
            ],
        },
        {
            items: productTypesMapped
                .filter(
                    (productType) => !productType.flag || featureFlags[productType.flag as keyof typeof featureFlags]
                )
                .map((productType) => {
                    const active = searchFilters.fileType === productType.value
                    return {
                        label: productType.label,
                        icon: active ? <IconCheck /> : <IconBlank />,
                        active,
                        'data-attr': `tree-filters-dropdown-menu-${productType.value}-button`,
                        onClick: () => toggleFileTypeFilter(productType.value),
                    }
                }),
        },
    ]
}
