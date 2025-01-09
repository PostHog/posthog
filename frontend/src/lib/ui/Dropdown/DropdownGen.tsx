'use client'

import * as React from 'react'

import { Button } from '../Button/Button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '../Command/Command'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '../Dropdown/Dropdown'

type DropdownItem = {
    type?: 'dropdown' | 'combobox'
    label: string
    value?: any
    items?: DropdownItem[]
    placeholder?: string
    defaultValue?: string
    onClick?: (value: any) => void
    buttonProps?: Omit<React.ComponentPropsWithoutRef<typeof Button>, 'children' | 'onClick'>
}
type DropdownGenProps = React.ComponentPropsWithoutRef<typeof DropdownMenuContent> & {
    button: React.ReactNode
    items: DropdownItem[]
    id: string
}

const DropdownGen = ({ button, items, id }: DropdownGenProps): JSX.Element => {
    const renderItems = (items: DropdownItem[]): JSX.Element[] => {
        return items.map((item, index): JSX.Element => {
            if (item.type === 'combobox') {
                return (
                    <DropdownMenuSub key={index}>
                        <DropdownMenuSubTrigger
                            buttonProps={{
                                hasIconLeft: item.buttonProps?.iconLeft ? true : false,
                                iconLeft: item.buttonProps?.iconLeft ? item.buttonProps?.iconLeft : undefined,
                                ...item.buttonProps,
                            }}
                        >
                            {item.label}
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <Command>
                                <CommandInput
                                    placeholder={item.placeholder}
                                    autoFocus
                                    id={`${id}-${index}-combobox-input`}
                                />
                                <CommandList>
                                    <CommandEmpty>No results found.</CommandEmpty>
                                    <CommandGroup>
                                        {item.items?.map((subItem, subIndex) => (
                                            <CommandItem
                                                key={subIndex}
                                                onSelect={() => subItem.onClick?.(subItem.value)}
                                                buttonProps={{
                                                    ...subItem.buttonProps,
                                                }}
                                            >
                                                {subItem.label}
                                            </CommandItem>
                                        ))}
                                    </CommandGroup>
                                </CommandList>
                            </Command>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                )
            }

            if (item.items) {
                return (
                    <DropdownMenuSub key={index}>
                        <DropdownMenuSubTrigger
                            buttonProps={{
                                hasIconLeft: item.buttonProps?.iconLeft ? true : false,
                                iconLeft: item.buttonProps?.iconLeft ? item.buttonProps?.iconLeft : undefined,
                                ...item.buttonProps,
                            }}
                        >
                            {item.label}
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>{renderItems(item.items)}</DropdownMenuSubContent>
                    </DropdownMenuSub>
                )
            }

            return (
                <DropdownMenuItem
                    key={index}
                    onSelect={() => item.onClick?.(item.value)}
                    buttonProps={{
                        hasIconLeft: item.buttonProps?.iconLeft ? true : false,
                        iconLeft: item.buttonProps?.iconLeft ? item.buttonProps?.iconLeft : undefined,
                        ...item.buttonProps,
                    }}
                >
                    {item.label}
                </DropdownMenuItem>
            )
        })
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>{button}</DropdownMenuTrigger>
            <DropdownMenuContent>
                {items.map((section, index) => (
                    <React.Fragment key={index}>
                        {index > 0 && <DropdownMenuSeparator />}
                        {renderItems([section])}
                    </React.Fragment>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export default DropdownGen
