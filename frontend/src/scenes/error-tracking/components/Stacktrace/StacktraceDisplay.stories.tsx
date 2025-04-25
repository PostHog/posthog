import { LemonCard } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'
import { TEST_EVENTS, TestEventNames } from 'scenes/error-tracking/__mocks__/events'
import { getExceptionAttributes } from 'scenes/error-tracking/utils'
import { sceneLogic } from 'scenes/sceneLogic'

import { mswDecorator } from '~/mocks/browser'
import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { HeaderRenderer, StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from './StacktraceBase'
import { StacktraceGenericDisplay } from './StacktraceGenericDisplay'
import { StacktraceTextDisplay } from './StacktraceTextDisplay'

const meta: Meta = {
    title: 'ErrorTracking/StacktraceDisplay',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        (Story: React.FC): JSX.Element => {
            sceneLogic.mount()
            return (
                <LemonCard hoverEffect={false} className="p-2 px-3 w-[900px]">
                    <Story />
                </LemonCard>
            )
        },
        mswDecorator({
            post: {
                'api/environments/:team_id/error_tracking/stack_frames/batch_get/': require('../../__mocks__/stack_frames/batch_get'),
            },
        }),
    ],
}

export default meta

////////////////////// Generic stacktraces

export function GenericDisplayPropertiesLoading(): JSX.Element {
    const props = defaultBaseProps(
        'python_resolved',
        {
            loading: true,
        },
        false
    )
    return <StacktraceGenericDisplay {...props} />
}

export function GenericDisplayEmpty(): JSX.Element {
    const props = defaultBaseProps(
        'javascript_empty',
        {
            loading: false,
        },
        false
    )
    return <StacktraceGenericDisplay {...props} />
}

export function GenericDisplayWithStacktrace(): JSX.Element {
    return <StacktraceWrapperAllEvents>{(props) => <StacktraceGenericDisplay {...props} />}</StacktraceWrapperAllEvents>
}

///////////////////// Text stacktraces

export function TextDisplayEmpty(): JSX.Element {
    const props = defaultBaseProps(
        'javascript_empty',
        {
            loading: false,
        },
        false
    )
    return <StacktraceTextDisplay {...props} />
}

export function TextDisplayPropertiesLoading(): JSX.Element {
    const props = defaultBaseProps(
        'javascript_resolved',
        {
            loading: true,
        },
        false
    )
    return <StacktraceTextDisplay {...props} />
}

export function TextDisplayWithStacktrace(): JSX.Element {
    return <StacktraceWrapperAllEvents>{(props) => <StacktraceTextDisplay {...props} />}</StacktraceWrapperAllEvents>
}

//////////////////// Utils

const issue = {
    id: '123',
    name: 'Issue Title',
    description: 'Issue Description',
    status: 'active',
    assignee: null,
    first_seen: '2022-01-05',
} as ErrorTrackingRelationalIssue

function defaultBaseProps(
    event_name: TestEventNames | null,
    overrideProps: Partial<StacktraceBaseDisplayProps> = {},
    issueLoading: boolean = false
): StacktraceBaseDisplayProps {
    const attributes = event_name ? getExceptionAttributes(TEST_EVENTS[event_name].properties) : null
    return {
        loading: false,
        showAllFrames: true,
        truncateMessage: true,
        attributes,
        renderLoading: (renderHeader: HeaderRenderer) =>
            renderHeader({
                type: issue?.name ?? undefined,
                value: issue?.description ?? undefined,
                loading: issueLoading,
            }),
        renderEmpty: () => <StacktraceEmptyDisplay />,
        ...overrideProps,
    } as StacktraceBaseDisplayProps
}

function StacktraceWrapperAllEvents({
    children,
}: {
    children: (props: StacktraceBaseDisplayProps) => JSX.Element
}): JSX.Element {
    const eventNames = Object.keys(TEST_EVENTS) as TestEventNames[]
    function getProps(eventName: TestEventNames): StacktraceBaseDisplayProps {
        return defaultBaseProps(
            eventName,
            {
                loading: false,
            },
            false
        )
    }
    return (
        <div className="space-y-4">
            {eventNames.map((name: TestEventNames) => {
                const props = getProps(name)
                return (
                    <LemonCard className="px-3 py-2" key={name}>
                        {children(props)}
                    </LemonCard>
                )
            })}
        </div>
    )
}
