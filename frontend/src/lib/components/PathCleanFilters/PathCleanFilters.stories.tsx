import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { PathCleaningFilter } from '~/types'

import { PathCleanFilters, PathCleanFiltersProps } from './PathCleanFilters'

type Story = StoryObj<typeof PathCleanFilters>
const meta: Meta<typeof PathCleanFilters> = {
    title: 'Filters/PathCleanFilters',
    component: PathCleanFilters,
}
export default meta

const Template: StoryFn<typeof PathCleanFilters> = (props: Partial<PathCleanFiltersProps>) => {
    const [filters, setFilters] = useState<PathCleaningFilter[]>([
        { alias: 'insights', regex: '/insights/w+/dashboard$' },
        { regex: '/feature_flags/d+$' },
        { alias: 'recordings' },
    ])

    return <PathCleanFilters filters={filters} setFilters={setFilters} {...props} />
}

export const Default: Story = Template.bind({})
Default.args = {}
