import { Meta } from '@storybook/react'

import { EmptyMessage } from './EmptyMessage'

const meta: Meta<typeof EmptyMessage> = {
    title: 'Components/Empty Message',
    component: EmptyMessage,
}
export default meta

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
