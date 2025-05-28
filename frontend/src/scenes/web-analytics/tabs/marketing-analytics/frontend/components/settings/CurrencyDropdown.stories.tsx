import { Meta } from '@storybook/react'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { CurrencyDropdown } from './CurrencyDropdown'

const meta: Meta = {
    title: 'Components/CurrencyDropdown',
    component: CurrencyDropdown,
}
export default meta

export function CurrencyDropdownStory(): JSX.Element {
    return <CurrencyDropdown value={'BRL' as CurrencyCode} onChange={() => {}} visible />
}
