import { Meta } from '@storybook/react'

import { LoadingBar } from './LoadingBar'

const meta: Meta<typeof LoadingBar> = {
    title: 'Lemon UI/LoadingBar',
    component: LoadingBar,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
    tags: ['autodocs'],
}
export default meta

export function Default(): JSX.Element {
    return <LoadingBar />
}

