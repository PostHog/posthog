import { Meta, StoryObj } from '@storybook/react'

import { SelectedPeopleList } from './SelectedPeopleList'

const meta: Meta<typeof SelectedPeopleList> = {
    title: 'Scenes-App/People/Cohorts/Selected People List',
    component: SelectedPeopleList,
    parameters: {
        layout: 'padded',
    },
}
export default meta

type Story = StoryObj<typeof SelectedPeopleList>

const noop = (): void => {}

export const WithPeople: Story = {
    args: {
        people: {
            '017cf78e-a849-0000-0000-01fe9b8d7233': 'Jane Doe',
            '01804f4e-0fb7-0000-0000-0db0398f4d98': 'John Smith',
            '0188f346-0564-0000-0000-16bc74aebc20': null,
        },
        onRemove: noop,
    },
}

export const Empty: Story = {
    args: {
        people: {},
        onRemove: noop,
    },
}
