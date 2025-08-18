import { useValues } from 'kea'

import { IconCheck, IconFilter } from '@posthog/icons'

import { IconBlank } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { fileSystemTypes } from '~/products'
import { FileSystemType } from '~/types'

interface FiltersDropdownProps {
    setSearchTerm: (searchTerm: string) => void
    searchTerm: string
}

const missingProductTypes: { value: string; label: string; flag?: string }[] = [
    { value: 'destination', label: 'Destinations' },
    { value: 'site_app', label: 'Site apps' },
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

export function TreeFiltersDropdownMenu({ setSearchTerm, searchTerm }: FiltersDropdownProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const removeTagsStarting = (str: string, tag: string): string =>
        str
            .split(' ')
            .filter((p) => !p.startsWith(tag))
            .join(' ')
            .trim()
    const removeTagsEquals = (str: string, tag: string): string =>
        str
            .split(' ')
            .filter((p) => p != tag)
            .join(' ')
            .trim()
    const addTag = (str: string, tag: string): string => `${str.trim()} ${tag.trim()}`.trim()

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive
                    iconOnly
                    data-attr="tree-filters-dropdown-menu-trigger-button"
                    tooltip="Tree filters"
                    tooltipPlacement="bottom"
                >
                    <IconFilter className="size-3 text-tertiary" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
                <DropdownMenuRadioGroup>
                    <DropdownMenuRadioItem
                        asChild
                        value="user:me"
                        onClick={() => {
                            setSearchTerm(
                                searchTerm.includes('user:me')
                                    ? removeTagsEquals(searchTerm, 'user:me')
                                    : addTag(searchTerm, 'user:me')
                            )
                        }}
                    >
                        <ButtonPrimitive
                            menuItem
                            data-attr="tree-filters-dropdown-menu-only-my-stuff-button"
                            active={searchTerm.includes('user:me')}
                        >
                            {searchTerm.includes('user:me') ? <IconCheck /> : <IconBlank />}
                            Only my stuff
                        </ButtonPrimitive>
                    </DropdownMenuRadioItem>
                    <DropdownMenuSeparator />
                    {productTypesMapped
                        .filter(
                            (productType) =>
                                !productType.flag || featureFlags[productType.flag as keyof typeof featureFlags]
                        )
                        .map((productType) => (
                            <DropdownMenuRadioItem
                                asChild
                                key={productType.value}
                                value={productType.value}
                                onClick={() => {
                                    setSearchTerm(
                                        searchTerm.includes(`type:${productType.value}`)
                                            ? removeTagsStarting(searchTerm, 'type:')
                                            : addTag(
                                                  removeTagsStarting(searchTerm, 'type:'),
                                                  `type:${productType.value}`
                                              )
                                    )
                                }}
                            >
                                <ButtonPrimitive
                                    menuItem
                                    data-attr={`tree-filters-dropdown-menu-${productType.value}-button`}
                                    active={searchTerm.includes(`type:${productType.value}`)}
                                >
                                    {searchTerm.includes(`type:${productType.value}`) ? <IconCheck /> : <IconBlank />}
                                    {productType.label}
                                </ButtonPrimitive>
                            </DropdownMenuRadioItem>
                        ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
