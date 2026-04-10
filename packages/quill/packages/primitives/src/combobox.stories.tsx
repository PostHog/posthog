import type { Meta, StoryObj } from '@storybook/react'
import React from 'react'

import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    ComboboxSeparator,
    ComboboxValue,
    useComboboxAnchor,
} from './combobox'
import { Item, ItemContent, ItemDescription, ItemTitle } from './item'

const meta = {
    title: 'Primitives/Combobox',
    component: Combobox,
    tags: ['autodocs'],
} satisfies Meta<typeof Combobox>

export default meta
type Story = StoryObj<typeof meta>

const frameworks = ['Next.js', 'SvelteKit', 'Nuxt.js', 'Remix', 'Astro', 'This will truncate in both the chip + list and still show chipClose'] as const

export const Default: Story = {
    render: () => {
        return (
            <div className="max-w-xs">
                <Combobox items={frameworks}>
                    <ComboboxInput placeholder="Select a framework" />
                    <ComboboxContent>
                        <ComboboxEmpty>No items found.</ComboboxEmpty>
                        <ComboboxList>
                            {(item: (typeof frameworks)[number]) => (
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

function MultipleComboboxInner(): React.ReactElement {
    const anchor = useComboboxAnchor()
    return (
        <React.Fragment>
            <ComboboxChips ref={anchor} className="max-w-xs">
                <ComboboxValue>
                    {(values) => (
                        <React.Fragment>
                            {values.map((value: string) => (
                                <ComboboxChip key={value} title={value}>{value}</ComboboxChip>
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
        </React.Fragment>
    )
}

export const Multiple: Story = {
    render: () => (
        <div className="max-w-xs">
            <Combobox multiple autoHighlight items={frameworks} defaultValue={[frameworks[0]]}>
                <MultipleComboboxInner />
            </Combobox>
        </div>
    ),
} satisfies Story

export const Clearable: Story = {
    render: () => {
        return (
            <div className="max-w-xs">
                <Combobox items={frameworks} defaultValue={frameworks[0]}>
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
        const timezones = [
            {
                value: 'Americas',
                items: [
                    '(GMT-5) New York',
                    '(GMT-8) Los Angeles',
                    '(GMT-6) Chicago',
                    '(GMT-5) Toronto',
                    '(GMT-8) Vancouver',
                    '(GMT-3) São Paulo',
                ],
            },
            {
                value: 'Europe',
                items: [
                    '(GMT+0) London',
                    '(GMT+1) Paris',
                    '(GMT+1) Berlin',
                    '(GMT+1) Rome',
                    '(GMT+1) Madrid',
                    '(GMT+1) Amsterdam',
                ],
            },
            {
                value: 'Asia/Pacific',
                items: [
                    '(GMT+9) Tokyo',
                    '(GMT+8) Shanghai',
                    '(GMT+8) Singapore',
                    '(GMT+4) Dubai',
                    '(GMT+11) Sydney',
                    '(GMT+9) Seoul',
                ],
            },
        ] as const

        return (
            <div className="max-w-xs">
                <Combobox items={timezones}>
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
        const countries = [
            { code: '', value: '', continent: '', label: 'Select country' },
            {
                code: 'ar',
                value: 'argentina',
                label: 'Argentina',
                continent: 'South America',
            },
            { code: 'au', value: 'australia', label: 'Australia', continent: 'Oceania' },
            { code: 'br', value: 'brazil', label: 'Brazil', continent: 'South America' },
            { code: 'ca', value: 'canada', label: 'Canada', continent: 'North America' },
            { code: 'cn', value: 'china', label: 'China', continent: 'Asia' },
            {
                code: 'co',
                value: 'colombia',
                label: 'Colombia',
                continent: 'South America',
            },
            { code: 'eg', value: 'egypt', label: 'Egypt', continent: 'Africa' },
            { code: 'fr', value: 'france', label: 'France', continent: 'Europe' },
            { code: 'de', value: 'germany', label: 'Germany', continent: 'Europe' },
            { code: 'it', value: 'italy', label: 'Italy', continent: 'Europe' },
            { code: 'jp', value: 'japan', label: 'Japan', continent: 'Asia' },
            { code: 'ke', value: 'kenya', label: 'Kenya', continent: 'Africa' },
            { code: 'mx', value: 'mexico', label: 'Mexico', continent: 'North America' },
            {
                code: 'nz',
                value: 'new-zealand',
                label: 'New Zealand',
                continent: 'Oceania',
            },
            { code: 'ng', value: 'nigeria', label: 'Nigeria', continent: 'Africa' },
            {
                code: 'za',
                value: 'south-africa',
                label: 'South Africa',
                continent: 'Africa',
            },
            { code: 'kr', value: 'south-korea', label: 'South Korea', continent: 'Asia' },
            {
                code: 'gb',
                value: 'united-kingdom',
                label: 'United Kingdom',
                continent: 'Europe',
            },
            {
                code: 'us',
                value: 'united-states',
                label: 'United States',
                continent: 'North America',
            },
        ]

        return (
            <div className="max-w-xs">
                <Combobox
                    items={countries.filter((country) => country.code !== '')}
                    itemToStringValue={(country: (typeof countries)[number]) => country.label}
                >
                    <ComboboxInput placeholder="Search countries..." className="max-w-xs" />
                    <ComboboxContent>
                        <ComboboxEmpty>No countries found.</ComboboxEmpty>
                        <ComboboxList>
                            {(country) => (
                                <ComboboxItem key={country.code} value={country} className="h-auto">
                                    <Item size="xs" className="p-0">
                                        <ItemContent variant="menuItem">
                                            <ItemTitle className="whitespace-nowrap">{country.label}</ItemTitle>
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
                <ComboboxInput placeholder="Select a framework" aria-invalid="true" className="max-w-xs" />
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
