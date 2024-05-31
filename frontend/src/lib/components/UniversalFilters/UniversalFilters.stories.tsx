import { Meta } from '@storybook/react'

import { UniversalFilters } from './UniversalFilters'

const meta: Meta<typeof UniversalFilters> = {
    title: 'Filters/UniversalFilters',
    component: UniversalFilters,
}
export default meta

export function Default(): JSX.Element {
    return <UniversalFilters />
}
