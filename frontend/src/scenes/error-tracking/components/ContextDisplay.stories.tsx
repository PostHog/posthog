import { LemonCard } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'
import { TEST_EVENTS, TestEventNames } from 'scenes/error-tracking/__mocks__/events'
import { getAdditionalProperties, getExceptionAttributes } from 'scenes/error-tracking/utils'

import { ContextDisplay, ContextDisplayProps } from './ContextDisplay'

const meta: Meta = {
    title: 'ErrorTracking/ContextDisplay',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        (Story: React.FC): JSX.Element => {
            return (
                <LemonCard hoverEffect={false} className="p-2 px-3 w-[900px]">
                    <Story />
                </LemonCard>
            )
        },
    ],
}

export default meta

///////////////////// Context Display

export function ContextDisplayEmpty(): JSX.Element {
    return <ContextDisplay attributes={null} additionalProperties={{}} loading={false} />
}

export function ContextDisplayWithStacktrace(): JSX.Element {
    return <ContextWrapperAllEvents>{(props) => <ContextDisplay {...props} />}</ContextWrapperAllEvents>
}

//////////////////// Utils

function getProps(event_name: TestEventNames | null, overrideProps: Record<string, unknown> = {}): ContextDisplayProps {
    const properties = event_name ? TEST_EVENTS[event_name].properties : null
    const attributes = properties ? getExceptionAttributes(properties) : null
    const additionalProperties = properties ? getAdditionalProperties(properties, true) : {}
    return {
        loading: false,
        attributes,
        additionalProperties,
        ...overrideProps,
    } as ContextDisplayProps
}

function ContextWrapperAllEvents({ children }: { children: (props: ContextDisplayProps) => JSX.Element }): JSX.Element {
    const eventNames = Object.keys(TEST_EVENTS) as TestEventNames[]
    return (
        <div className="space-y-4">
            {eventNames.map((name: TestEventNames) => {
                const props = getProps(name)
                return (
                    <div className="px-3 py-2" key={name}>
                        {children(props)}
                    </div>
                )
            })}
        </div>
    )
}
