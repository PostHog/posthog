import { Meta } from '@storybook/react'

import { EmptyMessage, EmptyMessageProps } from './EmptyMessage'

const meta: Meta<EmptyMessageProps> = {
    title: 'Components/Empty Message',
    component: EmptyMessage,
}
export default meta

export function EmptyMessage_(): JSX.Element {
    return (
        <EmptyMessage
            title="The data is not here"
            description="It really could be anywhere. Nobody knows where it went."
            buttonText="Check the map"
            buttonTo="https://www.google.com/maps"
        />
    )
}
