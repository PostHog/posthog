import type { Meta, StoryObj } from '@storybook/react-vite'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from './collapsible'
import { Combobox, ComboboxList, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxChip, ComboboxChipsInput, ComboboxValue, ComboboxChips, useComboboxAnchor, ComboboxGroup, ComboboxLabel, ComboboxCollection, ComboboxSeparator } from './combobox'
import React from 'react'
import { Item, ItemTitle, ItemContent, ItemDescription } from './item'

const meta = {
    title: 'Primitives/Combobox',
    component: Combobox,
    tags: ['autodocs'],
} satisfies Meta<typeof Combobox>

export default meta
type Story = StoryObj<typeof meta>


const frameworks = [
    "Next.js",
    "SvelteKit",
    "Nuxt.js",
    "Remix",
    "Astro",
] as const

export const Default: Story = {
    render: () => {
        const [open, setOpen] = React.useState(true)
        return (
            <div className="max-w-sm">
                <Combobox items={frameworks} open={open} onOpenChange={setOpen}>
                    <ComboboxInput placeholder="Select a framework" />
                    <ComboboxContent>
                        <ComboboxEmpty>No items found.</ComboboxEmpty>
                        <ComboboxList>
                            {(item) => (
                                <ComboboxItem key={item} value={item}>
                                    {item}
                                </ComboboxItem>
                            )}
                        </ComboboxList>
                    </ComboboxContent>
                </Combobox>
            </div>
        )
    },
} satisfies Story


export const Multiple: Story = {
    render: () => {
        const anchor = useComboboxAnchor()
        const [open, setOpen] = React.useState(true)
        return (
            <div className="max-w-sm">

                <Combobox
                    multiple
                    autoHighlight
                    items={frameworks}
                    defaultValue={[frameworks[0]]}
                    open={open}
                    onOpenChange={setOpen}
                >
                    <ComboboxChips ref={anchor} className="max-w-xs">
                        <ComboboxValue>
                            {(values) => (
                                <React.Fragment>
                                    {values.map((value: string) => (
                                        <ComboboxChip key={value}>{value}</ComboboxChip>
                                    ))}
                                    <ComboboxChipsInput />
                                </React.Fragment>
                            )}
                        </ComboboxValue>
                    </ComboboxChips>
                    <ComboboxContent anchor={anchor}>
                        <ComboboxEmpty>No items found.</ComboboxEmpty>
                        <ComboboxList>
                            {(item) => (
                                <ComboboxItem key={item} value={item}>
                                    {item}
                                </ComboboxItem>
                            )}
                        </ComboboxList>
                    </ComboboxContent>
                </Combobox>
            </div>
        )
    },
} satisfies Story

export const Clearable: Story = {
    render: () => {
        const [open, setOpen] = React.useState(true)
        return (
            <div className="max-w-sm">
                <Combobox items={frameworks} defaultValue={frameworks[0]} open={open} onOpenChange={setOpen}>
                    <ComboboxInput placeholder="Select a framework" showClear className="max-w-xs" />
                    <ComboboxContent>
                        <ComboboxEmpty>No items found.</ComboboxEmpty>
                        <ComboboxList>
                            {(item) => (
                                <ComboboxItem key={item} value={item}>
                                    {item}
                                </ComboboxItem>
                            )}
                        </ComboboxList>
                    </ComboboxContent>
                </Combobox>
            </div>
        )
    },
} satisfies Story

export const GroupsAndSeparators: Story = {
    render: () => {
        const [open, setOpen] = React.useState(true)
        const timezones = [
            {
                value: "Americas",
                items: [
                    "(GMT-5) New York",
                    "(GMT-8) Los Angeles",
                    "(GMT-6) Chicago",
                    "(GMT-5) Toronto",
                    "(GMT-8) Vancouver",
                    "(GMT-3) São Paulo",
                ],
            },
            {
                value: "Europe",
                items: [
                    "(GMT+0) London",
                    "(GMT+1) Paris",
                    "(GMT+1) Berlin",
                    "(GMT+1) Rome",
                    "(GMT+1) Madrid",
                    "(GMT+1) Amsterdam",
                ],
            },
            {
                value: "Asia/Pacific",
                items: [
                    "(GMT+9) Tokyo",
                    "(GMT+8) Shanghai",
                    "(GMT+8) Singapore",
                    "(GMT+4) Dubai",
                    "(GMT+11) Sydney",
                    "(GMT+9) Seoul",
                ],
            },
        ] as const;

        return (
            <div className="max-w-sm">
                <Combobox items={timezones} open={open} onOpenChange={setOpen}>
                    <ComboboxInput placeholder="Select a timezone" className="max-w-xs" />
                    <ComboboxContent>
                        <ComboboxEmpty>No timezones found.</ComboboxEmpty>
                        <ComboboxList>
                            {(group, index) => (
                                <ComboboxGroup key={group.value} items={group.items}>
                                    <ComboboxLabel>{group.value}</ComboboxLabel>
                                    <ComboboxCollection>
                                        {(item) => (
                                            <ComboboxItem key={item} value={item}>
                                                {item}
                                            </ComboboxItem>
                                        )}
                                    </ComboboxCollection>
                                    {index < timezones.length - 1 && <ComboboxSeparator />}
                                </ComboboxGroup>
                            )}
                        </ComboboxList>
                    </ComboboxContent>
                </Combobox>
            </div>
        )
    },
} satisfies Story

export const CustomItems: Story = {
    render: () => {
        const [open, setOpen] = React.useState(true)
        const countries = [
            { code: "", value: "", continent: "", label: "Select country" },
            {
                code: "ar",
                value: "argentina",
                label: "Argentina",
                continent: "South America",
            },
            { code: "au", value: "australia", label: "Australia", continent: "Oceania" },
            { code: "br", value: "brazil", label: "Brazil", continent: "South America" },
            { code: "ca", value: "canada", label: "Canada", continent: "North America" },
            { code: "cn", value: "china", label: "China", continent: "Asia" },
            {
                code: "co",
                value: "colombia",
                label: "Colombia",
                continent: "South America",
            },
            { code: "eg", value: "egypt", label: "Egypt", continent: "Africa" },
            { code: "fr", value: "france", label: "France", continent: "Europe" },
            { code: "de", value: "germany", label: "Germany", continent: "Europe" },
            { code: "it", value: "italy", label: "Italy", continent: "Europe" },
            { code: "jp", value: "japan", label: "Japan", continent: "Asia" },
            { code: "ke", value: "kenya", label: "Kenya", continent: "Africa" },
            { code: "mx", value: "mexico", label: "Mexico", continent: "North America" },
            {
                code: "nz",
                value: "new-zealand",
                label: "New Zealand",
                continent: "Oceania",
            },
            { code: "ng", value: "nigeria", label: "Nigeria", continent: "Africa" },
            {
                code: "za",
                value: "south-africa",
                label: "South Africa",
                continent: "Africa",
            },
            { code: "kr", value: "south-korea", label: "South Korea", continent: "Asia" },
            {
                code: "gb",
                value: "united-kingdom",
                label: "United Kingdom",
                continent: "Europe",
            },
            {
                code: "us",
                value: "united-states",
                label: "United States",
                continent: "North America",
            },
        ]

        return (
            <div className="max-w-sm">
                <Combobox
                    open={open}
                    onOpenChange={setOpen}
                    items={countries.filter((country) => country.code !== "")}
                    itemToStringValue={(country: (typeof countries)[number]) => country.label}
                    isItemEqualToValue={(a: (typeof countries)[number], b: (typeof countries)[number]) => a.code === b.code}
                >
                    <ComboboxInput placeholder="Search countries..." className="max-w-xs"/>
                    <ComboboxContent>
                        <ComboboxEmpty>No countries found.</ComboboxEmpty>
                        <ComboboxList>
                            {(country) => (
                                <ComboboxItem key={country.code} value={country}>
                                    <Item size="xs" className="p-0 pr-8">
                                        <ItemContent>
                                            <ItemTitle className="whitespace-nowrap">
                                                {country.label}
                                            </ItemTitle>
                                            <ItemDescription>
                                                {country.continent} ({country.code})
                                            </ItemDescription>
                                        </ItemContent>
                                    </Item>
                                </ComboboxItem>
                            )}
                        </ComboboxList>
                    </ComboboxContent>
                </Combobox>
            </div>
        )
    },
} satisfies Story


export const Invalid: Story = {
    render: () => {
        return (
            <Combobox items={frameworks}>
                <ComboboxInput placeholder="Select a framework" aria-invalid="true" className="max-w-xs"/>
                <ComboboxContent>
                    <ComboboxEmpty>No items found.</ComboboxEmpty>
                    <ComboboxList>
                        {(item) => (
                            <ComboboxItem key={item} value={item}>
                                {item}
                            </ComboboxItem>
                        )}
                    </ComboboxList>
                </ComboboxContent>
            </Combobox>
        )
    },
} satisfies Story