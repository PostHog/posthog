import { LemonCard } from '@posthog/lemon-ui'
import { TEST_EVENTS, TestEventNames } from 'scenes/error-tracking/__mocks__/events'
import { getExceptionAttributes } from 'scenes/error-tracking/utils'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { HeaderRenderer, StacktraceBaseDisplayProps, StacktraceEmptyDisplay } from './StacktraceBase'

const issue = {
    id: '123',
    name: 'Issue Title',
    description: 'Issue Description',
    status: 'active',
    assignee: null,
    first_seen: '2022-01-05',
} as ErrorTrackingRelationalIssue

export function defaultBaseProps(
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
        renderEmpty: (renderHeader) => (
            <>
                {renderHeader({
                    type: issue?.name ?? undefined,
                    value: issue?.description ?? undefined,
                    loading: issueLoading,
                })}
                <StacktraceEmptyDisplay />
            </>
        ),
        ...overrideProps,
    } as StacktraceBaseDisplayProps
}

export function StacktraceWrapperAllEvents({
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
