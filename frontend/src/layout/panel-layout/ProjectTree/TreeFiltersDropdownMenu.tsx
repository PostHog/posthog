import { IconCheck, IconFilter } from '@posthog/icons'
import { useValues } from 'kea'
import { IconBlank } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
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
                    className="z-2 shrink-0 motion-safe:transition-opacity duration-[50ms] group-hover/lemon-tree-button-group:opacity-100 aria-expanded:opacity-100"
                    data-attr="tree-filters-dropdown-menu-trigger-button"
                >
                    <IconFilter className="size-3 text-tertiary" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="end" side="bottom" className="max-w-[250px]">
                <DropdownMenuGroup>
                    <DropdownMenuItem
                        onClick={(e) => {
                            e.preventDefault()
                            setSearchTerm(
                                searchTerm.includes('user:me')
                                    ? removeTagsEquals(searchTerm, 'user:me')
                                    : addTag(searchTerm, 'user:me')
                            )
                        }}
                    >
                        <ButtonPrimitive menuItem data-attr="tree-filters-dropdown-menu-only-my-stuff-button">
                            {searchTerm.includes('user:me') ? <IconCheck /> : <IconBlank />}
                            Only my stuff
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    {productTypesMapped
                        .filter(
                            (productType) =>
                                !productType.flag || featureFlags[productType.flag as keyof typeof featureFlags]
                        )
                        .map((productType) => (
                            <DropdownMenuItem
                                key={productType.value}
                                onClick={(e) => {
                                    e.preventDefault()
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
                                >
                                    {searchTerm.includes(`type:${productType.value}`) ? <IconCheck /> : <IconBlank />}
                                    {productType.label}
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        ))}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
