import { getRuntimeFromLib } from 'lib/components/Errors/utils'
import { TEST_EVENTS, TestEventNames } from 'scenes/error-tracking/__mocks__/events'

import { StacktraceBaseDisplayProps } from './StacktraceBase'

export function defaultBaseProps(
    event_name: TestEventNames | null,
    overrideProps: Partial<StacktraceBaseDisplayProps> = {}
): StacktraceBaseDisplayProps {
    const event = event_name ? TEST_EVENTS[event_name] : null
    const exceptionList = event?.properties['$exception_list'] || []
    const fingerprintRecords = event?.properties['$fingerprint_records'] || []
    const runtime = getRuntimeFromLib(event?.properties['$lib'])
    return {
        loading: false,
        showAllFrames: true,
        truncateMessage: true,
        exceptionList,
        fingerprintRecords,
        runtime,
        renderLoading: () => <div>Loading...</div>,
        renderEmpty: () => <div>No data available</div>,
        ...overrideProps,
    } as StacktraceBaseDisplayProps
}
