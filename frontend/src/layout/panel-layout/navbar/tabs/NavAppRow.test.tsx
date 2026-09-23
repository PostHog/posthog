import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, TeamType } from '~/types'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { NavAppRow } from './NavAppRow'

const defaultAccess = Object.fromEntries(
    Object.values(AccessControlResourceType).map((type) => [type, AccessControlLevel.Editor])
) as Record<AccessControlResourceType, AccessControlLevel>

describe('NavAppRow', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/file_system_shortcut/': { results: [] } } })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_enabled: true } as TeamType)
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            effective_resource_access_control: defaultAccess,
        }
    })

    afterEach(cleanup)

    it('closes the temporary navigation when selecting the current app', () => {
        router.actions.push('/project/1/feature_flags')
        panelLayoutLogic.mount()
        panelLayoutLogic.actions.toggleLayoutNavCollapsed(true)
        panelLayoutLogic.actions.setNavOverlayOpen(true)
        const { container } = render(
            <NavAppRow item={{ path: 'Feature flags', iconType: 'feature_flag', href: '/feature_flags' }} />
        )

        fireEvent.click(container.querySelector('[data-attr="nav-apps-item"]')!)

        expect(panelLayoutLogic.values.isNavOverlayOpen).toBe(false)
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(true)
    })

    it('disables navigation and starring when access to a product is denied', () => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            effective_resource_access_control: { ...defaultAccess, feature_flag: AccessControlLevel.None },
        }
        const { container, getByLabelText } = render(
            <NavAppRow
                item={{
                    path: 'Feature flags',
                    iconType: 'feature_flag',
                    href: '/feature_flags',
                    sceneKey: 'FeatureFlags',
                }}
            />
        )
        const row = container.querySelector<HTMLButtonElement>('[data-attr="nav-apps-item"]')
        expect(row?.disabled).toBe(true)
        expect(row?.hasAttribute('href')).toBe(false)
        expect(getByLabelText('Open Feature flags menu').getAttribute('aria-disabled')).toBe('true')
    })

    it('adds and removes a star through the existing shortcut API', async () => {
        const create = jest.fn(() => [
            201,
            { id: 'star-test', path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' },
        ])
        const remove = jest.fn(() => [204])
        useMocks({
            post: { '/api/environments/:team_id/file_system_shortcut/': create },
            delete: { '/api/environments/:team_id/file_system_shortcut/star-test/': remove },
        })
        const { getByLabelText, getByText, findByText } = render(
            <NavAppRow
                item={{ path: 'Feature flags', type: 'feature_flag', iconType: 'feature_flag', href: '/feature_flags' }}
            />
        )
        await waitFor(() => expect(projectTreeDataLogic.values.shortcutDataLoading).toBe(false))
        fireEvent.click(getByLabelText('Open Feature flags menu'))
        const add = await findByText('Add to starred')
        fireEvent.click(add)
        fireEvent.click(add)
        await waitFor(() => expect(projectTreeDataLogic.values.shortcutData).toHaveLength(1))
        expect(create).toHaveBeenCalledTimes(1)
        fireEvent.click(getByLabelText('Open Feature flags menu'))
        fireEvent.click(await findByText('Remove from starred'))
        await waitFor(() => expect(projectTreeDataLogic.values.shortcutData).toHaveLength(0))
        expect(remove).toHaveBeenCalledTimes(1)
        fireEvent.click(getByLabelText('Open Feature flags menu'))
        expect(getByText('Add to starred')).toBeTruthy()
    })
})
