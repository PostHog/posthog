import { UniqueIdentifier } from '@dnd-kit/core'
import type { Meta, StoryObj } from '@storybook/react'

import { VerticalNestedDND, VerticalNestedDNDProps } from './VerticalNestedDND'

interface ExampleSubItem {
    id: UniqueIdentifier
}
interface ExampleItem {
    id: UniqueIdentifier
    items?: ExampleSubItem[]
}
let counter = 0

type Story = StoryObj<VerticalNestedDNDProps<ExampleSubItem, ExampleItem>>
const meta: Meta<VerticalNestedDNDProps<ExampleSubItem, ExampleItem>> = {
    title: 'Components/VerticalNestedDND',
    component: VerticalNestedDND,
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
    tags: ['autodocs'],
    render: (props) => {
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
    },
}
export default meta

export const Base: Story = {
    args: {},
}
