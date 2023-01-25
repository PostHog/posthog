import { ComponentMeta, ComponentStory } from '@storybook/react'
import { useState } from 'react'
import { PathCleaningFilter } from '~/types'

import { PathCleanFilters, PathCleanFiltersProps } from './PathCleanFilters'

export default {
    title: 'Filters/PathCleanFilters',
    component: PathCleanFilters,
} as ComponentMeta<typeof PathCleanFilters>

const Template: ComponentStory<typeof PathCleanFilters> = (props: Partial<PathCleanFiltersProps>) => {
    const [filters, setFilters] = useState<PathCleaningFilter[]>([
        { alias: 'insights', regex: '/insights/w+/dashboard$' },
        { regex: '/feature_flags/d+$' },
        { alias: 'recordings' },
    ])
    return <PathCleanFilters filters={filters} setFilters={setFilters} {...props} />
}

export const Default = Template.bind({})
Default.args = {}
