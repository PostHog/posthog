import { Combobox } from '@base-ui/react/combobox'
import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useRef, useState } from 'react'

import { IconCheck, IconPlusSmall, IconSearch, IconX } from '@posthog/icons'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'
import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { globalModalsLogic } from '~/layout/GlobalModals'
import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { AccessLevelIndicator } from '~/layout/navigation/AccessLevelIndicator'
import { AvailableFeature, OrganizationBasicType } from '~/types'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { newAccountMenuLogic } from './newAccountMenuLogic'

interface OrgListItem {
    type: 'org'
    id: string
    org: OrganizationBasicType
    isCurrent: boolean
    isDisabled: boolean
    disabledReason?: string
}

interface CreateOrgItem {
    type: 'create'
    id: 'create-new-org'
    label: string
}

type ListItem = OrgListItem | CreateOrgItem

export function OrgSwitcher(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateOrganizationModal } = useActions(globalModalsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { updateCurrentOrganization } = useActions(userLogic)
    const { closeOrgSwitcher } = useActions(newAccountMenuLogic)

    const [searchValue, setSearchValue] = useState('')
    const inputRef = useRef<HTMLInputElement>(null!)

    const allOrgItems: OrgListItem[] = useMemo(() => {
        const items: OrgListItem[] = []

        if (currentOrganization) {
            items.push({
                type: 'org',
                id: currentOrganization.id,
                org: currentOrganization,
                isCurrent: true,
                isDisabled: false,
            })
        }

        for (const org of otherOrganizations) {
            items.push({
                type: 'org',
                id: org.id,
                org,
                isCurrent: false,
                isDisabled: org.is_active === false,
                disabledReason: org.is_not_active_reason || 'Organization is disabled',
            })
        }

        return items
    }, [currentOrganization, otherOrganizations])

    const filteredItems = useMemo(() => {
        const searchLower = searchValue.trim().toLowerCase()

        // Filter org items
        const filteredOrgs = searchLower
            ? allOrgItems.filter((item) => item.org.name.toLowerCase().includes(searchLower))
            : allOrgItems

        // Create the "create" item - show different label based on search
        const createItem: CreateOrgItem = {
            type: 'create',
            id: 'create-new-org',
            label: 'New organization',
            // TODO: Uncomment this when we have a way to create organizations with a name
            // label: searchValue.trim() ? `Create '${searchValue.trim()}'` : 'New organization',
        }

        return [...filteredOrgs, createItem] as ListItem[]
    }, [allOrgItems, searchValue])

    const currentOrgItem = filteredItems.find((o): o is OrgListItem => o.type === 'org' && o.isCurrent)
    const otherOrgItems = filteredItems
        .filter((o): o is OrgListItem => o.type === 'org' && !o.isCurrent)
        .sort((a, b) => a.org.name.localeCompare(b.org.name))
    const createItem = filteredItems.find((o): o is CreateOrgItem => o.type === 'create')

    const handleItemClick = useCallback(
        (item: ListItem) => {
            if (item.type === 'create') {
                guardAvailableFeature(
                    AvailableFeature.ORGANIZATIONS_PROJECTS,
                    () => {
                        showCreateOrganizationModal()
                    },
                    { guardOnCloud: false }
                )
                closeOrgSwitcher()
            } else if (!item.isCurrent && !item.isDisabled) {
                closeOrgSwitcher()
                updateCurrentOrganization(item.org.id)
            }
        },
        [closeOrgSwitcher, updateCurrentOrganization, guardAvailableFeature, showCreateOrganizationModal]
    )

    const getItemString = useCallback((item: ListItem | null): string => {
        if (!item) {
            return ''
        }
        if (item.type === 'create') {
            return item.label
        }
        return item.org.name
    }, [])

    const canCreateOrg = preflight?.can_create_org !== false

    return (
        <Combobox.Root
            items={filteredItems}
            filter={null}
            itemToStringValue={getItemString}
            inline
            defaultOpen
            autoHighlight
        >
            <div className="flex flex-col overflow-hidden">
                {/* Search Input */}
                <div className="p-2 border-b border-primary">
                    <label className="group input-like flex gap-1 items-center relative w-full bg-fill-input border border-primary focus-within:ring-primary py-1 px-2">
                        <Combobox.Icon
                            className="size-5"
                            render={<IconSearch className="text-tertiary group-focus-within:text-primary" />}
                        />
                        <Combobox.Input
                            ref={inputRef}
                            value={searchValue}
                            onChange={(e) => setSearchValue(e.target.value)}
                            aria-label="Search organizations"
                            placeholder="Search organizations..."
                            className="w-full px-1 py-1 text-sm focus:outline-none border-transparent"
                            autoFocus
                        />
                        {searchValue && (
                            <Combobox.Clear
                                render={
                                    <ButtonPrimitive
                                        iconOnly
                                        size="sm"
                                        onClick={() => setSearchValue('')}
                                        aria-label="Clear search"
                                        className="-mr-1"
                                    >
                                        <IconX className="size-4 text-tertiary" />
                                    </ButtonPrimitive>
                                }
                            />
                        )}
                    </label>
                </div>

                {/* Results */}
                <ScrollableShadows
                    direction="vertical"
                    styledScrollbars
                    className="flex-1 overflow-y-auto max-h-[400px]"
                >
                    <Combobox.List className="flex flex-col gap-px p-2">
                        {/* Current Organization */}
                        {currentOrgItem && (
                            <Combobox.Group items={[currentOrgItem]}>
                                <Combobox.Collection>
                                    {(item: OrgListItem) => (
                                        <Combobox.Item
                                            key={item.id}
                                            value={item}
                                            onClick={() => handleItemClick(item)}
                                            disabled
                                            render={(props) => (
                                                <ButtonPrimitive
                                                    {...props}
                                                    disabled
                                                    data-disabled="true"
                                                    menuItem
                                                    active
                                                    fullWidth
                                                >
                                                    <IconCheck className="text-tertiary" />
                                                    <UploadedLogo
                                                        size="xsmall"
                                                        name={item.org.name}
                                                        entityId={item.org.id}
                                                        mediaId={item.org.logo_media_id}
                                                    />
                                                    <span className="truncate">{item.org.name}</span>
                                                    <div className="ml-auto">
                                                        <AccessLevelIndicator organization={item.org} />
                                                    </div>
                                                </ButtonPrimitive>
                                            )}
                                        />
                                    )}
                                </Combobox.Collection>
                            </Combobox.Group>
                        )}

                        {/* Other Organizations */}
                        {otherOrgItems.length > 0 && (
                            <Combobox.Group items={otherOrgItems}>
                                <Combobox.Collection>
                                    {(item: OrgListItem) => (
                                        <Combobox.Item
                                            key={item.id}
                                            value={item}
                                            onClick={() => handleItemClick(item)}
                                            render={(props) => (
                                                <ButtonPrimitive
                                                    {...props}
                                                    menuItem
                                                    fullWidth
                                                    disabled={item.isDisabled}
                                                    tooltip={item.isDisabled ? item.disabledReason : undefined}
                                                    tooltipPlacement="right"
                                                >
                                                    <IconBlank />
                                                    <UploadedLogo
                                                        size="xsmall"
                                                        name={item.org.name}
                                                        entityId={item.org.id}
                                                        mediaId={item.org.logo_media_id}
                                                    />
                                                    <span className="truncate">{item.org.name}</span>
                                                    <div className="ml-auto">
                                                        <AccessLevelIndicator organization={item.org} />
                                                    </div>
                                                </ButtonPrimitive>
                                            )}
                                        />
                                    )}
                                </Combobox.Collection>
                            </Combobox.Group>
                        )}

                        {/* Create New Organization */}
                        {createItem && (
                            <Combobox.Group items={[createItem]}>
                                <Combobox.Collection>
                                    {(item: CreateOrgItem) => (
                                        <Combobox.Item
                                            key={item.id}
                                            value={item}
                                            onClick={() => handleItemClick(item)}
                                            render={(props) => (
                                                <ButtonPrimitive
                                                    {...props}
                                                    menuItem
                                                    fullWidth
                                                    disabled={!canCreateOrg}
                                                    tooltip={
                                                        !canCreateOrg
                                                            ? 'You do not have permission to create an organization'
                                                            : undefined
                                                    }
                                                    tooltipPlacement="right"
                                                >
                                                    <IconPlusSmall className="text-tertiary" />
                                                    <span className="truncate">{item.label}</span>
                                                </ButtonPrimitive>
                                            )}
                                        />
                                    )}
                                </Combobox.Collection>
                            </Combobox.Group>
                        )}
                    </Combobox.List>
                </ScrollableShadows>

                {/* Footer */}
                <div className="menu-legend border-t border-primary p-1">
                    <div className="px-2 py-1 text-xxs text-tertiary font-medium flex items-center gap-2">
                        <span>
                            <KeyboardShortcut arrowup arrowdown preserveOrder /> navigate
                        </span>
                        <span>
                            <KeyboardShortcut enter /> select
                        </span>
                        <span>
                            <KeyboardShortcut escape /> close
                        </span>
                    </div>
                </div>
            </div>
        </Combobox.Root>
    )
}
