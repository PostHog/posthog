import { IconSearch } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuContent,
    FilterCheckboxSubMenu,
    FilterClearItem,
    FilterMenuTrigger,
    FilterSearchSubMenu,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    InputGroupText,
} from '@posthog/quill'

import { fullName } from 'lib/utils/strings'

import { AccessControlLevel, APIScopeObject } from '~/types'

import type { AccessControlFiltersProps } from './AccessControlFilters'

/** Search, and beside it one menu with a row per filter. */
export function QuillAccessControlFilters(props: AccessControlFiltersProps): JSX.Element {
    const { roleIds, memberIds, resourceKeys, ruleLevels } = props.filters
    const subjectIds = props.activeTab === 'roles' ? roleIds : props.activeTab === 'members' ? memberIds : []
    const filtersActive = subjectIds.length > 0 || resourceKeys.length > 0 || ruleLevels.length > 0

    return (
        <div className="flex flex-wrap items-center gap-2">
            <InputGroup size="sm" className="w-64 max-w-full">
                <InputGroupAddon align="inline-start">
                    <InputGroupText>
                        <IconSearch />
                    </InputGroupText>
                </InputGroupAddon>
                <InputGroupInput
                    type="search"
                    aria-label="Search"
                    placeholder="Search"
                    value={props.searchText}
                    onChange={(event: React.ChangeEvent<HTMLInputElement>) => props.setSearchText(event.target.value)}
                />
            </InputGroup>

            <DropdownMenu>
                <FilterMenuTrigger active={filtersActive} />
                <DropdownMenuContent align="start" className="min-w-64">
                    {props.activeTab === 'roles' && props.canUseRoles && (
                        <FilterSearchSubMenu
                            label="Role"
                            allLabel="All roles"
                            pluralNoun="roles"
                            options={props.roles.map((role) => ({ value: role.id, label: role.name }))}
                            selected={roleIds}
                            onChange={(values) => props.setFilters({ roleIds: values })}
                            searchPlaceholder="Filter by roles…"
                            emptyText="No options found"
                        />
                    )}

                    {props.activeTab === 'members' && (
                        <FilterSearchSubMenu
                            label="Member"
                            allLabel="All members"
                            pluralNoun="members"
                            options={props.members.map((member) => ({
                                value: member.id,
                                label: fullName(member.user) || member.user.email,
                            }))}
                            selected={memberIds}
                            onChange={(values) => props.setFilters({ memberIds: values })}
                            searchPlaceholder="Filter by members…"
                            emptyText="No options found"
                        />
                    )}

                    <FilterSearchSubMenu
                        label="Product"
                        allLabel="All products"
                        pluralNoun="products"
                        options={props.resources
                            .filter((resource) => resource.key !== 'project')
                            .map((resource) => ({ value: resource.key, label: resource.label }))}
                        selected={resourceKeys}
                        onChange={(values) => props.setFilters({ resourceKeys: values as APIScopeObject[] })}
                        searchPlaceholder="Filter by products…"
                        emptyText="No options found"
                    />

                    <FilterCheckboxSubMenu<AccessControlLevel>
                        label="Access"
                        allLabel="Any access"
                        pluralNoun="levels"
                        options={props.ruleOptions.map((option) => ({ value: option.key, label: option.label }))}
                        selected={ruleLevels}
                        onChange={(values) => props.setFilters({ ruleLevels: values })}
                    />

                    <FilterClearItem
                        active={filtersActive}
                        onClear={() =>
                            props.setFilters({ roleIds: [], memberIds: [], resourceKeys: [], ruleLevels: [] })
                        }
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
