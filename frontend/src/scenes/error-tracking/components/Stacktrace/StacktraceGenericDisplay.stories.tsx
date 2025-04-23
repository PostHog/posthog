import { LemonCard } from '@posthog/lemon-ui'
import { Meta } from '@storybook/react'
import { sceneLogic } from 'scenes/sceneLogic'

import { mswDecorator } from '~/mocks/browser'

// import { results as stackframeResults } from '../../__mocks__/stack_frames/batch_get'
import { StacktraceEmptyDisplay } from './StacktraceBase'
import { StacktraceGenericDisplay, StacktraceGenericExceptionHeader } from './StacktraceGenericDisplay'
import { defaultBaseProps } from './utils.test'

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
const issue = {
    id: '123',
    name: 'Issue Title',
    description: 'Issue Description',
    status: 'active',
    assignee: null,
    first_seen: '2022-01-05',
}

type LoadingProps = {
    loading: boolean
    truncate: boolean
}

function getGenericLoadingRenderer({
    loading = false,
    truncate = true,
}: Partial<LoadingProps> = {}): () => JSX.Element {
    function renderLoading(): JSX.Element {
        return (
            <StacktraceGenericExceptionHeader
                type={issue.name}
                value={issue.description}
                loading={loading}
                truncate={truncate}
            />
        )
    }
    return renderLoading
}

function getGenericEmptyRenderer(): () => JSX.Element {
    function renderEmpty(): JSX.Element {
        return (
            <div>
                <StacktraceGenericExceptionHeader
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

// Generic stacktrace
export function GenericDisplayFullLoading(): JSX.Element {
    const props = defaultBaseProps('javascript_empty', {
        loading: true,
        renderLoading: getGenericLoadingRenderer({ loading: true }),
        renderEmpty: getGenericEmptyRenderer(),
    })
    return <StacktraceGenericDisplay {...props} />
}

export function GenericDisplayPropertiesLoading(): JSX.Element {
    const props = defaultBaseProps('python_resolved', {
        loading: true,
        renderLoading: getGenericLoadingRenderer({ loading: false }),
        renderEmpty: getGenericEmptyRenderer(),
    })
    return <StacktraceGenericDisplay {...props} />
}

export function GenericDisplayEmpty(): JSX.Element {
    const props = defaultBaseProps(null, {
        loading: false,
        renderLoading: getGenericLoadingRenderer({ loading: false }),
        renderEmpty: getGenericEmptyRenderer(),
    })
    return <StacktraceGenericDisplay {...props} />
}

export function GenericDisplayWithStacktrace(): JSX.Element {
    const props = defaultBaseProps('javascript_resolved', {
        showAllFrames: true,
        truncateMessage: false,
        renderLoading: getGenericLoadingRenderer({ loading: false }),
        renderEmpty: getGenericEmptyRenderer(),
    })
    return <StacktraceGenericDisplay {...props} />
}
