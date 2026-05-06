import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { RealtimeNotificationPreferences } from './RealtimeNotificationPreferences'

describe('<RealtimeNotificationPreferences />', () => {
    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
        organizationLogic.mount()
        userLogic.actions.loadUserSuccess({
            active_realtime_notification_types: ['comment_mention'],
            notification_settings: { realtime_notifications_disabled: {} },
        } as any)
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            id: 'org-1',
            name: 'Org',
            teams: [
                { id: 1, name: 'Project A' },
                { id: 2, name: 'Project B' },
            ],
        } as any)
    })

    it('renders one row per active project with the active types as children', () => {
        render(<RealtimeNotificationPreferences />)
        expect(screen.getByText('Project A')).toBeInTheDocument()
        expect(screen.getByText('Project B')).toBeInTheDocument()
        expect(screen.getAllByText('Comment mentions')).toHaveLength(2)
    })

    it('toggling a single type dispatches updateRealtimeNotificationForTeam', async () => {
        render(<RealtimeNotificationPreferences />)
        const checkbox = screen.getAllByRole('checkbox', { name: /Comment mentions/i })[0]
        await expectLogic(userLogic, () => userEvent.click(checkbox)).toDispatchActions([
            userLogic.actionCreators.updateRealtimeNotificationForTeam('comment_mention', 1, false),
        ])
    })

    it('clicking a project parent dispatches updateRealtimeNotificationForProject with disable', async () => {
        render(<RealtimeNotificationPreferences />)
        const projectCheckbox = screen.getAllByRole('checkbox', { name: /Project A/i })[0]
        await expectLogic(userLogic, () => userEvent.click(projectCheckbox)).toDispatchActions([
            userLogic.actionCreators.updateRealtimeNotificationForProject(1, ['comment_mention'], false),
        ])
    })
})
