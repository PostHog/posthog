import { LemonCard } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'
import { sceneLogic } from 'scenes/sceneLogic'

import { mswDecorator } from '~/mocks/browser'

import { defaultBaseProps, StacktraceWrapperAllEvents } from './__stories_utils'
import { StacktraceTextDisplay } from './StacktraceTextDisplay'

const meta: Meta = {
    title: 'ErrorTracking/StacktraceTextDisplay',
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

// Text stacktrace
// export function TextDisplayFullLoading(): JSX.Element {
//     const props = defaultBaseProps(
//         'python_resolved',
//         {
//             loading: true,
//         },
//         true
//     )
//     return <StacktraceTextDisplay {...props} />
// }

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
