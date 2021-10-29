import { posthog } from '../src/utils/posthog'
import { statusReport } from '../src/utils/status-report'

jest.mock('../src/utils/posthog')

describe('status report', () => {
    beforeEach(() => {
        posthog.capture = jest.fn()
    })

    test('status report keeps track of plugin duration metrics per team', () => {
        statusReport.startStatusReportSchedule()
        statusReport.addToTimeSpentRunningPlugins(1, 1200, 'processEvent')
        statusReport.addToTimeSpentRunningPlugins(1, 800, 'processEvent')
        statusReport.addToTimeSpentRunningPlugins(2, 3000, 'onEvent')
        statusReport.addToTimeSpentRunningPlugins(2, 3000, 'onSnapshot')
        statusReport.stopStatusReportSchedule()

        expect(posthog.capture).toHaveBeenCalledTimes(2)

        expect(posthog.capture).toHaveBeenNthCalledWith(1, '$plugin_running_duration', {
            onEvent_time_ms: 0,
            onEvent_time_seconds: 0,
            onSnapshot_time_ms: 0,
            onSnapshot_time_seconds: 0,
            pluginTask_time_ms: 0,
            pluginTask_time_seconds: 0,
            processEvent_time_ms: 2000,
            processEvent_time_seconds: 2,
            team: 1,
            total_time_ms: 2000,
            total_time_seconds: 2,
        })

        expect(posthog.capture).toHaveBeenNthCalledWith(2, '$plugin_running_duration', {
            onEvent_time_ms: 3000,
            onEvent_time_seconds: 3,
            onSnapshot_time_ms: 3000,
            onSnapshot_time_seconds: 3,
            pluginTask_time_ms: 0,
            pluginTask_time_seconds: 0,
            processEvent_time_ms: 0,
            processEvent_time_seconds: 0,
            team: 2,
            total_time_ms: 6000,
            total_time_seconds: 6,
        })
    })
})
