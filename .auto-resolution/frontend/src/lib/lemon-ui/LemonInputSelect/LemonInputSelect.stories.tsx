import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { capitalizeFirstLetter } from 'lib/utils'

import { ProfilePicture } from '../ProfilePicture'
import { LemonInputSelect } from './LemonInputSelect'

const names = [
    'ben',
    'marius',
    'paul',
    'tiina',
    'tim',
    'james',
    'neil',
    'tom',
    'annika',
    'thomas',
    'eric',
    'yakko',
    'manoel',
    'leon',
    'lottie',
    'charles',
]

type Story = StoryObj<typeof LemonInputSelect>
const meta: Meta<typeof LemonInputSelect> = {
    title: 'Lemon UI/Lemon Input Select',
    component: LemonInputSelect,
    args: {
        options: names.map((x, i) => ({
            key: `user-${i}`,
            labelComponent: (
                <span className="flex gap-2 items-center">
                    <ProfilePicture
                        user={{
                            first_name: x,
                            email: `${x}@posthog.com`,
                        }}
                        size="sm"
                    />
                    <span>
                        {capitalizeFirstLetter(x)} <b>{`<${x}@posthog.com>`}</b>
                    </span>
                </span>
            ),
            label: `${capitalizeFirstLetter(x)} <${x}@posthog.com>`,
        })),
    },
    tags: ['autodocs'],
}
export default meta

export const Default: Story = {
    args: {
        placeholder: 'Pick one email',
        mode: 'single',
    },
}

export const MultipleSelect: Story = {
    args: {
        placeholder: 'Pick email addresses',
        mode: 'multiple',
    },
}

export const MultipleSelectWithCustom: Story = {
    args: {
        placeholder: 'Enter URLs',
        mode: 'multiple',
        allowCustomValues: true,
        options: [
            {
                key: 'http://posthog.com/docs',
                label: 'http://posthog.com/docs',
            },
            {
                key: 'http://posthog.com/pricing',
                label: 'http://posthog.com/pricing',
            },

            {
                key: 'http://posthog.com/products',
                label: 'http://posthog.com/products',
            },
        ],
    },
}

export const Disabled: Story = {
    args: {
        mode: 'single',
        placeholder: 'Disabled...',
        disabled: true,
    },
}

export const Loading: Story = {
    args: {
        mode: 'single',
        placeholder: 'Loading with options...',
        loading: true,
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const EmptyLoading: Story = {
    args: {
        mode: 'single',
        placeholder: 'Loading without options...',
        options: [],
        loading: true,
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const NoOptions: Story = {
    args: {
        mode: 'multiple',
        allowCustomValues: true,
        placeholder: 'No options...',
        options: [],
    },
}

export const SingleOptionWithCustom: Story = {
    args: {
        mode: 'single',
        allowCustomValues: true,
        placeholder: 'Only one option allowed but can be custom',
    },
}

export const PrefilledManyValues: Story = {
    args: {
        mode: 'multiple',
        allowCustomValues: true,
        value: names.map((_, i) => `user-${i}`),
    },
}

export const WithSelectAllAndClear: Story = {
    args: {
        mode: 'multiple',
        bulkActions: 'select-and-clear-all',
    },
}

export const WithClearOnly: Story = {
    args: {
        mode: 'multiple',
        bulkActions: 'clear-all',
    },
}

export const CountModeAllSelected: Story = {
    args: {
        mode: 'multiple',
        displayMode: 'count',
        value: names.map((_, i) => `user-${i}`),
    },
}

export const CountModePartiallySelected: Story = {
    args: {
        mode: 'multiple',
        displayMode: 'count',
        value: names.slice(0, 10).map((_, i) => `user-${i}`),
    },
}

export const CountModeNoneSelected: Story = {
    args: {
        mode: 'multiple',
        displayMode: 'count',
        value: [],
    },
}

export const CountModeWithSelectClear: Story = {
    args: {
        mode: 'multiple',
        displayMode: 'count',
        bulkActions: 'select-and-clear-all',
        value: names.slice(0, 5).map((_, i) => `user-${i}`),
    },
}

// New stories showcasing typed values support
export const TypedValuesBooleanExample: StoryObj = {
    render: () => {
        const [value, setValue] = useState<(boolean | string)[]>([])

        const handleChange = (newValue: (boolean | string)[]): void => {
            setValue(newValue)
        }

        return (
            <div className="space-y-4">
                <LemonInputSelect<boolean | string>
                    mode="multiple"
                    placeholder="Select boolean or string values"
                    options={[
                        { key: 'bool-true', label: 'Boolean True', value: true },
                        { key: 'bool-false', label: 'Boolean False', value: false },
                        { key: 'some-variant', label: 'String Variant', value: 'some-variant' },
                        { key: 'string-true', label: 'String "true"', value: 'true' },
                    ]}
                    value={value}
                    onChange={handleChange}
                    className="w-140"
                />
                <div className="bg-accent-highlight-secondary p-3 rounded">
                    <strong>Selected values:</strong> {JSON.stringify(value)} <br />
                    <strong>Types:</strong> [{value.map((v) => typeof v).join(', ')}]
                    <br />
                    <em>Check browser console for onChange logs!</em>
                </div>
            </div>
        )
    },
    parameters: {
        docs: {
            description: {
                story: 'Demonstrates typed values support with boolean and string types. Notice how the onChange callback receives the original typed values (true, false, "some-variant") rather than just strings. Check the browser console and the display below to see the typed values!',
            },
        },
    },
}

export const TypedValuesBackwardsCompatibility: StoryObj = {
    render: () => {
        const [value, setValue] = useState<string[]>([])

        const handleChange = (newValue: string[]): void => {
            setValue(newValue)
        }

        return (
            <div className="space-y-4">
                <LemonInputSelect
                    mode="multiple"
                    placeholder="Select string options (backwards compatible)"
                    options={[
                        { key: 'option1', label: 'Option 1' },
                        { key: 'option2', label: 'Option 2' },
                        { key: 'option3', label: 'Option 3' },
                    ]}
                    value={value}
                    onChange={handleChange}
                    className="w-140"
                />
                <div className="bg-accent-highlight-secondary p-3 rounded">
                    <strong>Selected values:</strong> {JSON.stringify(value)} <br />
                    <strong>Types:</strong> [{value.map((v) => typeof v).join(', ')}]
                    <br />
                    <em>Works exactly as before - no breaking changes! Check browser console for onChange logs!</em>
                </div>
            </div>
        )
    },
    parameters: {
        docs: {
            description: {
                story: 'Shows backwards compatibility - existing string-only usage continues to work exactly as before. All values are strings and the component behaves identically to the previous version.',
            },
        },
    },
}
