import { Meta } from '@storybook/react'
import {
    BodyDisplay,
    HeadersDisplay,
    ItemPerformanceEvent,
} from 'scenes/session-recordings/player/inspector/components/ItemPerformanceEvent'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta<typeof ItemPerformanceEvent> = {
    title: 'Components/ItemPerformanceEvent',
    component: ItemPerformanceEvent,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

export function InitialHeadersDisplay(): JSX.Element {
    return <HeadersDisplay request={undefined} response={undefined} isInitial={true} />
}

export function InitialBodyDisplay(): JSX.Element {
    return (
        <BodyDisplay
            content={undefined}
            headers={undefined}
            emptyMessage="Response captured before PostHog was initialized"
        />
    )
}
