import { Meta } from '@storybook/react'
import { useState } from 'react'

import { FilterCheckboxList, type FilterCheckboxListProps } from './FilterCheckboxList'

const OPTIONS = [
    { key: 'first', label: 'First option' },
    { key: 'second', label: 'Second option' },
    { key: 'third', label: 'Third option' },
] as const

type OptionKey = (typeof OPTIONS)[number]['key']

const meta: Meta<FilterCheckboxListProps<OptionKey>> = {
    title: 'Components/Filter Checkbox List',
    component: FilterCheckboxList,
}
export default meta

export function Default(): JSX.Element {
    const [value, setValue] = useState<OptionKey[]>(['second'])
    return (
        <div className="w-80">
            <FilterCheckboxList options={OPTIONS} value={value} onChange={setValue} />
        </div>
    )
}
