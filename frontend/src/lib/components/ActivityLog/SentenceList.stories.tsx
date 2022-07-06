import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { SentenceList, SentenceListProps } from './SentenceList'

export default {
    title: 'Components/SentenceList',
    component: SentenceList,
} as ComponentMeta<typeof SentenceList>

const Template: ComponentStory<typeof SentenceList> = (props: SentenceListProps) => {
    return <SentenceList {...props} />
}

export const FullSentence = Template.bind({})
FullSentence.args = {
    prefix: 'Bob',
    suffix: 'on feature flag cool-flag',
    listParts: [
        'changed description to "something cool"',
        'changed name to "woop"',
        'changed rollout percentage to 52%',
    ],
}

export const OneAction = Template.bind({})
OneAction.args = { listParts: ['changed description to "something cool"'] }

export const TwoActions = Template.bind({})
TwoActions.args = { listParts: ['changed description to "something cool"', 'changed name to "woop"'] }

export const ThreeActions = Template.bind({})
ThreeActions.args = {
    listParts: [
        'changed description to "something cool"',
        'changed name to "woop"',
        'changed rollout percentage to 52%',
    ],
}
