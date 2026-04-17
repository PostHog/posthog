import type { Meta, StoryObj } from '@storybook/react'
import { Plus } from 'lucide-react'
import React from 'react'

import { Button } from './button'
import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxListFooter,
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

// "Input inside popup" pattern — the ComboboxInput lives inside ComboboxContent
// (the popup), not outside. A plain button triggers the popup. Useful when the
// trigger should be a compact chip or button, not a full-width input. See
// https://base-ui.com/react/components/combobox#input-inside-popup
export const InputInsidePopup: Story = {
    render: () => {
        const [open, setOpen] = React.useState(false)
        const [value, setValue] = React.useState<string | null>(null)
        const triggerRef = React.useRef<HTMLButtonElement>(null)
        return (
            <div className="max-w-xs">
                <Combobox
                    items={frameworks}
                    open={open}
                    onOpenChange={setOpen}
                    value={value}
                    onValueChange={setValue}
                >
                    <Button
                        ref={triggerRef}
                        variant="outline"
                        size="sm"
                        onClick={() => setOpen((prev) => !prev)}
                    >
                        {value ?? 'Select framework'}
                    </Button>
                    <ComboboxContent anchor={triggerRef}>
                        <ComboboxInput placeholder="Search..." showTrigger={false} />
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

const manyItems = [
    'Next.js',
    'SvelteKit',
    'Nuxt.js',
    'Remix',
    'Astro',
    'Gatsby',
    'Vite',
    'Parcel',
    'Webpack',
    'Rollup',
    'esbuild',
    'Turbopack',
    'Create React App',
    'Angular CLI',
    'Ember CLI',
    'Solid Start',
    'Qwik City',
    'Fresh',
    'Hono',
    'Redwood',
] as const

export const InputInsidePopupOverflow: Story = {
    render: () => {
        const [open, setOpen] = React.useState(false)
        const [value, setValue] = React.useState<string | null>(null)
        const triggerRef = React.useRef<HTMLButtonElement>(null)
        return (
            <div className="max-w-xs">
                <Combobox
                    items={manyItems}
                    open={open}
                    onOpenChange={setOpen}
                    value={value}
                    onValueChange={setValue}
                >
                    <Button
                        ref={triggerRef}
                        variant="outline"
                        size="sm"
                        onClick={() => setOpen((prev) => !prev)}
                    >
                        {value ?? 'Select framework'}
                    </Button>
                    <ComboboxContent anchor={triggerRef}>
                        <ComboboxInput placeholder="Search..." showTrigger={false} />
                        <ComboboxEmpty>No items found.</ComboboxEmpty>
                        <ComboboxList>
                            {(item: (typeof manyItems)[number]) => (
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

// Action item as the last ComboboxItem inside ComboboxList — arrow-key navigable.
// ComboboxListFooter wraps it with `sticky bottom-0` so it pins below the scrollable
// items. The sentinel value is intercepted in onValueChange to run the action
// instead of selecting. In production, use custom filtering (filter={null} +
// filteredItems) to keep the action visible regardless of search input.
const CREATE_ACTION = 'Create new'

export const InputInsidePopupWithFooter: Story = {
    render: () => {
        const [open, setOpen] = React.useState(false)
        const [value, setValue] = React.useState<string | null>(null)
        const triggerRef = React.useRef<HTMLButtonElement>(null)
        const allItems = [...manyItems, CREATE_ACTION]
        return (
            <div className="max-w-xs">
                <Combobox
                    items={allItems}
                    open={open}
                    onOpenChange={setOpen}
                    value={value}
                    onValueChange={(val) => {
                        if (val === CREATE_ACTION) {
                            // eslint-disable-next-line no-console
                            console.log('Create new clicked')
                            return
                        }
                        setValue(val)
                    }}
                >
                    <Button
                        ref={triggerRef}
                        variant="outline"
                        size="sm"
                        onClick={() => setOpen((prev) => !prev)}
                    >
                        {value ?? 'Select framework'}
                    </Button>
                    <ComboboxContent anchor={triggerRef}>
                        <ComboboxInput placeholder="Search..." showTrigger={false} />
                        <ComboboxEmpty>No items found.</ComboboxEmpty>
                        <ComboboxList>
                            {(item: string) =>
                                item === CREATE_ACTION ? (
                                    <ComboboxListFooter key="footer">
                                        <ComboboxItem value={CREATE_ACTION}>
                                            <Plus className="size-3" />
                                            {CREATE_ACTION}
                                        </ComboboxItem>
                                    </ComboboxListFooter>
                                ) : (
                                    <ComboboxItem key={item} value={item}>
                                        {item}
                                    </ComboboxItem>
                                )
                            }
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
