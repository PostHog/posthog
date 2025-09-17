import type { Meta } from '@storybook/react'

import { SearchAutocomplete } from './SearchAutocomplete'

const meta = {
    title: 'UI/SearchAutocomplete',
    component: SearchAutocomplete as any,
    tags: ['autodocs'],
} satisfies Meta<typeof SearchAutocomplete>

export default meta

export function Default(): JSX.Element {
    return (
        <div className="flex flex-col gap-4 max-w-lg">
            <SearchAutocomplete
                inputPlaceholder="Search for food"
                searchData={[
                    [
                        // Item to filter by
                        {
                            value: 'type',
                            label: 'type',
                            hint: 'Search by type',
                        },
                        // Suggestions once type is satisfied
                        [
                            { value: 'fruit', label: 'Fruit', hint: 'hint for fruit' },
                            { value: 'vegetable', label: 'Vegetable', hint: 'hint for vegetable' },
                            { value: 'meat', label: 'Meat', hint: 'hint for meat' },
                        ],
                        // Hint once type is satisfied
                        "I'm a hint for type, type a type",
                    ],
                    [
                        // Item to filter by
                        {
                            value: 'name',
                            label: 'name',
                            hint: 'Search by name',
                        },
                        // Suggestions once name is satisfied
                        undefined,
                        // Hint once name is satisfied
                        'I have no suggestions, but type any name',
                    ],
                    [
                        // Item to filter by
                        {
                            value: 'color',
                            label: 'color',
                            hint: 'Search by color',
                        },
                        // Suggestions once color is satisfied
                        [
                            { value: 'red', label: 'Red', hint: 'hint for red' },
                            { value: 'green', label: 'Green', hint: 'hint for green' },
                            { value: 'blue', label: 'Blue', hint: 'hint for blue' },
                        ],
                        // Hint once color is satisfied
                        "I'm a hint for color, type a color",
                    ],
                ]}
            />
        </div>
    )
}
