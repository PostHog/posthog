import { LemonCard } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'
import { sceneLogic } from 'scenes/sceneLogic'

import { mswDecorator } from '~/mocks/browser'

import { defaultBaseProps, StacktraceWrapperAllEvents } from './__stories_utils'
import { StacktraceGenericDisplay } from './StacktraceGenericDisplay'

const meta: Meta = {
    title: 'ErrorTracking/StacktraceGenericDisplay',
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

// Generic stacktrace
export function GenericDisplayFullLoading(): JSX.Element {
    const props = defaultBaseProps(
        'javascript_empty',
        {
            loading: true,
        },
        true
    )
    return <StacktraceGenericDisplay {...props} />
}

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
        null,
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
