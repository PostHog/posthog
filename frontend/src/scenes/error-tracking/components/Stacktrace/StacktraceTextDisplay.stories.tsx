import { LemonCard } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'
import { sceneLogic } from 'scenes/sceneLogic'

import { mswDecorator } from '~/mocks/browser'

import { StacktraceEmptyDisplay } from './StacktraceBase'
import { StacktraceTextDisplay, StacktraceTextExceptionHeader } from './StacktraceTextDisplay'
import { defaultBaseProps } from './utils.test'

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
export function TextDisplayFullLoading(): JSX.Element {
    const props = defaultBaseProps('python_resolved', {
        loading: true,
        renderLoading: getTextLoadingRenderer({ loading: true }),
        renderEmpty: getTextEmptyRenderer(),
    })
    return <StacktraceTextDisplay {...props} />
}

export function TextDisplayPropertiesLoading(): JSX.Element {
    const props = defaultBaseProps('javascript_resolved', {
        loading: true,
        renderLoading: getTextLoadingRenderer({ loading: false }),
        renderEmpty: getTextEmptyRenderer(),
    })
    return <StacktraceTextDisplay {...props} />
}

export function TextDisplayWithStacktrace(): JSX.Element {
    const props = defaultBaseProps('node_unresolved', {
        loading: false,
        renderLoading: getTextLoadingRenderer({ loading: false }),
        renderEmpty: getTextEmptyRenderer(),
    })
    return <StacktraceTextDisplay {...props} />
}

type LoadingProps = {
    loading: boolean
    truncate: boolean
}

const issue = {
    id: '123',
    name: 'Issue Title',
    description: 'Issue Description',
    status: 'active',
    assignee: null,
    first_seen: '2022-01-05',
}

// Renderer
function getTextLoadingRenderer({ loading = false, truncate = false }: Partial<LoadingProps> = {}): () => JSX.Element {
    function renderLoading(): JSX.Element {
        return (
            <StacktraceTextExceptionHeader
                type={issue.name}
                value={issue.description}
                loading={loading}
                truncate={truncate}
            />
        )
    }
    return renderLoading
}

function getTextEmptyRenderer(): () => JSX.Element {
    function renderEmpty(): JSX.Element {
        return (
            <div>
                <StacktraceTextExceptionHeader
                    type={issue.name}
                    value={issue.description}
                    loading={false}
                    truncate={true}
                />
                <StacktraceEmptyDisplay />
            </div>
        )
    }
    return renderEmpty
}
