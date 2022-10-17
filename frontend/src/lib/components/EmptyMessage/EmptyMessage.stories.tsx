import { ComponentMeta } from '@storybook/react'

import { EmptyMessage } from './EmptyMessage'

export default {
    title: 'Components/Empty Message',
    component: EmptyMessage,
} as ComponentMeta<typeof EmptyMessage>

export function EmptyMessage_(): JSX.Element {
    return (
        <EmptyMessage
            title="The data is not here"
            description="It really could be anywhere. Nobody knows where it is."
            buttonText="Check the map"
            buttonTo="https://www.google.com/maps"
        />
    )
}
