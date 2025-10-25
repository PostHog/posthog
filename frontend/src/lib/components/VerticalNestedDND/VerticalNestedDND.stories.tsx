import { UniqueIdentifier } from '@dnd-kit/core'
import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { VerticalNestedDND, VerticalNestedDNDProps } from './VerticalNestedDND'

type Story = StoryObj<typeof VerticalNestedDND>
const meta: Meta<typeof VerticalNestedDND> = {
    title: 'Components/VerticalNestedDND',
    component: VerticalNestedDND,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
    tags: ['autodocs'],
}
export default meta

interface ExampleSubItem {
    id: UniqueIdentifier
}
interface ExampleItem {
    id: UniqueIdentifier
    items?: ExampleSubItem[]
}
let counter = 0

const Template: StoryFn<typeof VerticalNestedDND> = (props: VerticalNestedDNDProps<ExampleSubItem, ExampleItem>) => {
    const starterData: ExampleItem[] = [
        {
            id: 'A',
            items: [
                {
                    id: 'A1',
                },
                {
                    id: 'A2',
                },
                {
                    id: 'A3',
                },
            ],
        },
        {
            id: 'B',
            items: [
                {
                    id: 'B1',
                },
                {
                    id: 'B2',
                },
                {
                    id: 'B3',
                },
            ],
        },
    ]

    const createNewChildItem = (): ExampleSubItem => {
        return {
            id: `new-${counter++}`,
        }
    }

    const createNewContainerItem = (): ExampleItem => {
        return {
            id: `new-${counter++}`,
            items: [],
        }
    }

    return (
        <VerticalNestedDND
            {...props}
            createNewChildItem={createNewChildItem}
            createNewContainerItem={createNewContainerItem}
            /* eslint-disable-next-line no-console */
            onChange={(items) => console.log('onChange', items)}
            initialItems={starterData}
        />
    )
}

export const Base: Story = Template.bind({})
