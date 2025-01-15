'use client'

import * as React from 'react'

import { Button } from '../Button/Button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '../Command/Command'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '../Dropdown/Dropdown'

type DropdownItem = {
    type?: 'dropdown' | 'combobox' | 'label' | 'divider'
    trigger?: string | React.ReactNode
    value?: any
    label?: string | React.ReactNode
    dropdownItems?: DropdownItem[]
    placeholder?: string
    defaultValue?: string
    onClick?: (value: any) => void
    disabled?: boolean
    buttonProps?: Omit<React.ComponentPropsWithoutRef<typeof Button>, 'children' | 'onClick'>
    sideAction?: {
        icon: React.ReactNode
        tooltip?: string
        tooltipPlacement?: 'top' | 'right' | 'bottom' | 'left'
        onClick: () => void
        disabled?: boolean
        disabledReason?: string
    }
    commandProps?: {
        placeholder?: string
        autoFocus?: boolean
        onSearch?: (value: string) => void
        emptyState?: React.ReactNode
    }
}

type DropdownGenProps = React.ComponentPropsWithoutRef<typeof DropdownMenuContent> & {
    trigger: React.ReactNode
    items: DropdownItem[]
    id: string
}

const filterItems = (items: (DropdownItem | false | undefined | null)[]): DropdownItem[] => {
    return items.filter((item): item is DropdownItem => !!item)
}

const DropdownGen = ({ trigger, items: dropdownItems, id, ...props }: DropdownGenProps): JSX.Element => {
    const renderItems = (items: DropdownItem[]): JSX.Element[] => {
        return items.map((item, index): JSX.Element => {
            if (item.type === 'combobox') {
                return (
                    <DropdownMenuSub key={index}>
                        {item.label && <DropdownMenuLabel>{item.label}</DropdownMenuLabel>}
                        <DropdownMenuSubTrigger
                            buttonProps={{
                                iconLeft: item.buttonProps?.iconLeft ? item.buttonProps?.iconLeft : undefined,
                                ...item.buttonProps,
                            }}
                            disabled={item.buttonProps?.disabledReason ? true : false}
                        >
                            {item.trigger || '<empty item.buttonText>'}
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <Command>
                                <CommandInput
                                    placeholder={item.commandProps?.placeholder || 'Search...'}
                                    autoFocus
                                    id={`${id}-${index}-combobox-input`}
                                />
                                <CommandList>
                                    <CommandEmpty>{item.commandProps?.emptyState || 'No items found'}</CommandEmpty>
                                    <CommandGroup>
                                        {item.dropdownItems &&
                                            filterItems(item.dropdownItems).map((subItem, subIndex) => (
                                                <React.Fragment key={subIndex}>
                                                    {subItem.type === 'divider' ? (
                                                        <DropdownMenuSeparator className="relative" />
                                                    ) : (
                                                        <CommandItem
                                                            key={subIndex}
                                                            onSelect={() => subItem.onClick?.(subItem.value)}
                                                            buttonProps={{
                                                                ...subItem.buttonProps,
                                                            }}
                                                            disabled={
                                                                subItem.buttonProps?.disabledReason ? true : false
                                                            }
                                                        >
                                                            {subItem.trigger}
                                                        </CommandItem>
                                                    )}
                                                </React.Fragment>
                                            ))}
                                    </CommandGroup>
                                </CommandList>
                            </Command>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                )
            }

            if (item.dropdownItems) {
                return (
                    <DropdownMenuSub key={index}>
                        {item.label && <DropdownMenuLabel>{item.label}</DropdownMenuLabel>}
                        <DropdownMenuSubTrigger
                            disabled={item.buttonProps?.disabledReason ? true : false}
                            buttonProps={{
                                iconLeft: item.buttonProps?.iconLeft ? item.buttonProps?.iconLeft : undefined,
                                ...item.buttonProps,
                            }}
                        >
                            {item.trigger}
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>{renderItems(filterItems(item.dropdownItems))}</DropdownMenuSubContent>
                    </DropdownMenuSub>
                )
            }

            if (item.type === 'label') {
                return <DropdownMenuLabel key={index}>{item.label}</DropdownMenuLabel>
            }

            if (item.type === 'divider') {
                return <DropdownMenuSeparator key={index} />
            }

            return (
                <DropdownMenuItem
                    key={index}
                    onSelect={() => item.onClick?.(item.value)}
                    buttonProps={{
                        iconLeft: item.buttonProps?.iconLeft ? item.buttonProps?.iconLeft : undefined,
                        ...item.buttonProps,
                    }}
                    disabled={item.buttonProps?.disabledReason ? true : false}
                >
                    {item.trigger}
                </DropdownMenuItem>
            )
        })
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
            <DropdownMenuContent {...props}>
                {filterItems(dropdownItems).map((section, index) => (
                    <React.Fragment key={index}>{renderItems([section])}</React.Fragment>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export default DropdownGen
