import type { Meta, StoryObj } from '@storybook/react'

import { Button } from './button'
import { ButtonGroup, ButtonGroupSeparator, ButtonGroupText } from './button-group'

const meta = {
    title: 'Primitives/Button Group',
    component: ButtonGroup,
    tags: ['autodocs'],
} satisfies Meta<typeof ButtonGroup>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <div className="flex flex-col gap-2">
            <ButtonGroup>
                <ButtonGroup>
                    <Button variant="outline">Button 1</Button>
                </ButtonGroup>
                <ButtonGroup>
                    <Button variant="outline">Button 2</Button>
                    <Button variant="outline">Button 3</Button>
                    <Button variant="outline">Button 4</Button>
                </ButtonGroup>
            </ButtonGroup>
            <ButtonGroup>
                <ButtonGroup>
                    <Button variant="outline">Button 2</Button>
                    <Button variant="outline">Button 4</Button>
                </ButtonGroup>
                <ButtonGroupSeparator />
                <ButtonGroup>
                    <Button variant="outline">Button 1</Button>
                </ButtonGroup>
                <ButtonGroup>
                    <ButtonGroupText>Some text</ButtonGroupText>
                </ButtonGroup>
                <ButtonGroupSeparator />
                <ButtonGroup>
                    <ButtonGroupText>Some text</ButtonGroupText>
                </ButtonGroup>
            </ButtonGroup>
        </div>
    ),
} satisfies Story
