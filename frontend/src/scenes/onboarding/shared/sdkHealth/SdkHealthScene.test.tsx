import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { getAllByDataAttr } from '~/test/byDataAttr'
import { initKeaTests } from '~/test/init'

import { sdkHealthLogic } from './sdkHealthLogic'
import { SdkHealthScene } from './SdkHealthScene'

const OUTDATED_REPORT = {
    health: 'warning',
    overall_health: 'needs_attention',
    needs_updating_count: 1,
    sdks: [
        {
            lib: 'web',
            is_outdated: true,
            is_old: false,
            needs_updating: true,
            migration_required: false,
            latest_version: '1.2.3',
            severity: 'warning',
            banners: ['posthog-js is 40 versions behind.'],
            outdated_traffic_alerts: [],
            releases: [],
        },
    ],
}

// LemonBanner renders its action twice, once per responsive breakpoint, so both copies carry the
// same data-attr and only the visible one is worth clicking.
function bannerAction(dataAttr: string): HTMLElement {
    return getAllByDataAttr(document.body, dataAttr)[0]
}

function mountWithOutdatedReport(): ReturnType<typeof sdkHealthLogic.build> {
    const logic = sdkHealthLogic()
    logic.mount()
    logic.actions.loadReportSuccess(OUTDATED_REPORT as any)
    return logic
}

describe('<SdkHealthScene />', () => {
    beforeEach(() => {
        // snoozedUntil is a `persist: true` reducer, so a previous test's snooze would otherwise
        // still be in localStorage when the next one mounts the logic.
        localStorage.clear()
        jest.useFakeTimers({ doNotFake: ['performance'] })
        jest.setSystemTime(new Date('2026-09-22'))
        useMocks({
            get: {
                '/api/projects/:team_id/sdk_health/report/': OUTDATED_REPORT,
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('replaces the update warning with the snoozed-until notice once snoozed', () => {
        mountWithOutdatedReport()
        render(<SdkHealthScene />)

        expect(screen.getByText('Time for an update!')).toBeInTheDocument()

        fireEvent.click(bannerAction('sdk-health-snooze-warning'))

        expect(screen.queryByText('Time for an update!')).toBeNull()
        expect(screen.getByText('Update warning snoozed')).toBeInTheDocument()
        expect(screen.getByText(/1 SDK still needs an update\. Snoozed until/)).toBeInTheDocument()
    })

    it('brings the update warning back when the snooze is lifted', () => {
        mountWithOutdatedReport()
        render(<SdkHealthScene />)

        fireEvent.click(bannerAction('sdk-health-snooze-warning'))
        fireEvent.click(bannerAction('sdk-health-unsnooze-warning'))

        expect(screen.getByText('Time for an update!')).toBeInTheDocument()
        expect(screen.queryByText('Update warning snoozed')).toBeNull()
    })

    it('ignores a snooze that has already expired', () => {
        const logic = mountWithOutdatedReport()
        logic.actions.snoozeSdkHealth()
        jest.setSystemTime(new Date('2027-01-01'))

        render(<SdkHealthScene />)

        expect(screen.getByText('Time for an update!')).toBeInTheDocument()
    })
})
