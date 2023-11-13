import { Meta } from '@storybook/react'

import { NewPropertyComponent } from './NewPropertyComponent'

const meta: Meta = {
    title: 'Persons/New Property Modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
export const NewProperty = (): JSX.Element => <NewPropertyComponent editProperty={() => {}} />
