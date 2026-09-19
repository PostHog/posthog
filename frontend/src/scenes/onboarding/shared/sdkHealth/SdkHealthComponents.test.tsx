import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import type { SdkHealthReportApi } from 'products/growth/frontend/generated/api.schemas'

import { SdkSection, SdkVersionStatusTag } from './SdkHealthComponents'
import { type SdkType, sdkHealthLogic } from './sdkHealthLogic'

const STATUS_REASON = 'Released 2 years ago. Upgrade recommended.'

const UNKNOWN_SDK = 'posthog-sdk-added-after-this-bundle' as SdkType

const unknownSdkReport: SdkHealthReportApi = {
    overall_health: 'needs_attention',
    health: 'warning',
    needs_updating_count: 1,
    team_sdk_count: 1,
    sdks: [
        {
            lib: UNKNOWN_SDK,
            readable_name: UNKNOWN_SDK,
            latest_version: '2.0.0',
            needs_updating: true,
            is_outdated: true,
            is_old: true,
            migration_required: false,
            severity: 'danger',
            reason: 'Outdated',
            banners: [],
            outdated_traffic_alerts: [],
            releases: [
                {
                    version: '1.0.0',
                    count: 12,
                    max_timestamp: '2026-09-07T12:43:00Z',
                    release_date: null,
                    days_since_release: null,
                    released_ago: null,
                    is_outdated: true,
                    is_old: true,
                    needs_updating: true,
                    is_current_or_newer: false,
                    status_reason: STATUS_REASON,
                    sql_query: '',
                    activity_page_url: '',
                },
            ],
        },
    ],
}

describe('SdkHealthComponents', () => {
    describe('SdkVersionStatusTag', () => {
        afterEach(() => {
            cleanup()
        })

        it('shows the status reason when the tag is clicked', async () => {
            render(
                <SdkVersionStatusTag type="danger" statusReason={STATUS_REASON}>
                    Outdated
                </SdkVersionStatusTag>
            )

            expect(screen.queryByText(STATUS_REASON)).toBeNull()

            fireEvent.click(screen.getByText('Outdated'))

            expect(await screen.findByText(STATUS_REASON)).toBeTruthy()
        })

        it('is focusable so keyboard users can reach the status reason too', () => {
            render(
                <SdkVersionStatusTag type="success" statusReason={STATUS_REASON}>
                    Current
                </SdkVersionStatusTag>
            )

            expect(screen.getByText('Current').getAttribute('tabindex')).toBe('0')
        })
    })

    describe('SdkSection', () => {
        beforeEach(() => {
            initKeaTests()
            sdkHealthLogic.mount()
            sdkHealthLogic.actions.loadReportSuccess(unknownSdkReport)
        })

        afterEach(() => {
            cleanup()
            sdkHealthLogic.unmount()
        })

        // An unguarded docs-links lookup threw here, and the error boundary blanked the whole scene.
        it('renders an SDK that is missing from the docs links map', () => {
            const { container } = render(<SdkSection sdkType={UNKNOWN_SDK} />)

            expect(within(container).getByText(UNKNOWN_SDK)).toBeTruthy()
            expect(within(container).getByText('1.0.0')).toBeTruthy()
            expect(within(container).queryByText('Releases')).toBeNull()
            expect(within(container).getByText('Docs').getAttribute('href')).toBe('https://posthog.com/docs/libraries')
        })
    })
})
