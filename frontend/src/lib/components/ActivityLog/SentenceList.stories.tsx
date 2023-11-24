import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { SentenceList, SentenceListProps } from './SentenceList'

type Story = StoryObj<typeof SentenceList>
const meta: Meta<typeof SentenceList> = {
    title: 'Components/SentenceList',
    component: SentenceList,
    parameters: {},
}
export default meta

const Template: StoryFn<typeof SentenceList> = (props: SentenceListProps) => {
    return <SentenceList {...props} />
}

export const FullSentence: Story = Template.bind({})
FullSentence.args = {
    prefix: 'Bob',
    suffix: 'on feature flag cool-flag',
    listParts: [
        'changed description to "something cool"',
        'changed name to "woop"',
        'changed rollout percentage to 52%',
    ],
}

export const OneAction: Story = Template.bind({})
OneAction.args = { listParts: ['changed description to "something cool"'] }

export const TwoActions: Story = Template.bind({})
TwoActions.args = { listParts: ['changed description to "something cool"', 'changed name to "woop"'] }

export const ThreeActions: Story = Template.bind({})
ThreeActions.args = {
    listParts: [
        'changed description to "something cool"',
        'changed name to "woop"',
        'changed rollout percentage to 52%',
    ],
}
