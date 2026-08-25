import { Meta, StoryFn } from '@storybook/react'
import { useMountedLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import { welcomeDialogLogic } from '../welcomeDialogLogic'
import { FlagshipProductsCard } from './FlagshipProductsCard'

const meta: Meta<typeof FlagshipProductsCard> = {
    title: 'Scenes-Other/Welcome/FlagshipProductsCard',
    component: FlagshipProductsCard,
    parameters: {
        layout: 'padded',
        testOptions: { include: false },
    },
    decorators: [mswDecorator({})],
}
export default meta

export const Default: StoryFn<typeof FlagshipProductsCard> = () => {
    useMountedLogic(welcomeDialogLogic)
    return (
        <div className="max-w-[608px]">
            <FlagshipProductsCard />
        </div>
    )
}
