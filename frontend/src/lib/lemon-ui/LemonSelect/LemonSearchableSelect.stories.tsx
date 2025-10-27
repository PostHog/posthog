import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonSearchableSelect, LemonSearchableSelectProps, LemonSelectOptions } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'

type Story = StoryObj<typeof LemonSearchableSelect>
const meta: Meta<typeof LemonSearchableSelect> = {
    title: 'Lemon UI/Lemon Searchable Select',
    component: LemonSearchableSelect,
    args: {
        options: [
            { value: 'husky', label: 'Husky' },
            { value: 'poodle', label: 'Poodle' },
            { value: 'labrador', label: 'Labrador' },
        ] as LemonSelectOptions<string>,
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonSearchableSelect> = (props: LemonSearchableSelectProps<any>) => {
    return (
        <div className="flex flex-row items-center w-full border p-4 gap-2">
            {(['small', 'medium', 'large', undefined] as const).map((size, index) => (
                <div className="flex flex-col" key={index}>
                    <h5>size={capitalizeFirstLetter(size || 'unspecified')}</h5>
                    <LemonSearchableSelect {...props} size={size} />
                </div>
            ))}
        </div>
    )
}

export const WithSearch: Story = Template.bind({})
WithSearch.args = {
    placeholder: 'Search and select a country',
    searchPlaceholder: 'Search countries...',
    options: [
        'Afghanistan',
        'Albania',
        'Algeria',
        'Andorra',
        'Angola',
        'Argentina',
        'Armenia',
        'Australia',
        'Austria',
        'Azerbaijan',
        'Bahrain',
        'Bangladesh',
        'Belarus',
        'Belgium',
        'Bolivia',
        'Bosnia and Herzegovina',
        'Brazil',
        'Bulgaria',
        'Cambodia',
        'Canada',
        'Chile',
        'China',
        'Colombia',
        'Croatia',
        'Cyprus',
        'Czech Republic',
        'Denmark',
        'Ecuador',
        'Egypt',
        'Estonia',
        'Finland',
        'France',
        'Germany',
        'Greece',
        'Hungary',
        'Iceland',
        'India',
        'Indonesia',
        'Iran',
        'Iraq',
        'Ireland',
        'Israel',
        'Italy',
        'Japan',
        'Kazakhstan',
        'Kenya',
        'Latvia',
        'Lithuania',
        'Malaysia',
        'Mexico',
        'Morocco',
        'Netherlands',
        'New Zealand',
        'Norway',
        'Pakistan',
        'Peru',
        'Philippines',
        'Poland',
        'Portugal',
        'Romania',
        'Russia',
        'Saudi Arabia',
        'Singapore',
        'Slovakia',
        'Slovenia',
        'South Africa',
        'South Korea',
        'Spain',
        'Sweden',
        'Switzerland',
        'Thailand',
        'Turkey',
        'Ukraine',
        'United Arab Emirates',
        'United Kingdom',
        'United States',
        'Vietnam',
    ].map((country) => ({ label: country, value: country.toLowerCase().replace(/\s+/g, '_') })),
}

export const WithSearchSections: Story = Template.bind({})
WithSearchSections.args = {
    placeholder: 'Search programming languages',
    searchPlaceholder: 'Search languages...',
    options: [
        {
            title: 'Frontend',
            options: [
                { label: 'JavaScript', value: 'javascript' },
                { label: 'TypeScript', value: 'typescript' },
                { label: 'React', value: 'react' },
                { label: 'Vue.js', value: 'vue' },
                { label: 'Angular', value: 'angular' },
            ],
        },
        {
            title: 'Backend',
            options: [
                { label: 'Python', value: 'python' },
                { label: 'Java', value: 'java' },
                { label: 'Go', value: 'go' },
                { label: 'Rust', value: 'rust' },
                { label: 'C++', value: 'cpp' },
            ],
        },
        {
            title: 'Database',
            options: [
                { label: 'PostgreSQL', value: 'postgresql' },
                { label: 'MySQL', value: 'mysql' },
                { label: 'MongoDB', value: 'mongodb' },
                { label: 'Redis', value: 'redis' },
            ],
        },
    ],
}
