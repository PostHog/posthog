import { Meta, StoryObj } from '@storybook/react'

import { BuyHedgehogCoffeeModal } from './BuyHedgehogCoffee'

const meta: Meta<typeof BuyHedgehogCoffeeModal> = {
    title: 'Components/Buy Hedgehog Coffee Modal',
    component: BuyHedgehogCoffeeModal,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
}
export default meta
type Story = StoryObj<typeof BuyHedgehogCoffeeModal>

const noop = (): void => {}

export const Coffee: Story = {
    render: () => (
        <div className="bg-default p-4">
            <BuyHedgehogCoffeeModal isOpen onClose={noop} onDonate={noop} variant="coffee" inline />
        </div>
    ),
}

export const Money: Story = {
    render: () => (
        <div className="bg-default p-4">
            <BuyHedgehogCoffeeModal isOpen onClose={noop} onDonate={noop} variant="money" inline />
        </div>
    ),
}
