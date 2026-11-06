import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, TeamType } from '~/types'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { NavProductRow } from './NavProductRow'
import { navProductsTabLogic } from './navProductsTabLogic'

const defaultAccess = Object.fromEntries(
    Object.values(AccessControlResourceType).map((type) => [type, AccessControlLevel.Editor])
) as Record<AccessControlResourceType, AccessControlLevel>

describe('NavProductRow', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/file_system_shortcut/': { results: [] } } })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_enabled: true } as TeamType)
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            effective_resource_access_control: defaultAccess,
        }
    })

    afterEach(cleanup)

    it('closes the temporary navigation when selecting the current product', () => {
        router.actions.push('/project/1/feature_flags')
        panelLayoutLogic.mount()
        panelLayoutLogic.actions.toggleLayoutNavCollapsed(true)
        panelLayoutLogic.actions.setNavOverlayOpen(true)
        const { container } = render(
            <NavProductRow item={{ path: 'Feature flags', iconType: 'feature_flag', href: '/feature_flags' }} />
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
            <NavProductRow
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
        expect(getByLabelText('Add to starred').getAttribute('aria-disabled')).toBe('true')
    })

    it('adds a star and removes it only after confirming', async () => {
        const [path, type, href] = ['Feature flags', 'feature_flag', '/feature_flags']
        const create = jest.fn(() => [201, { id: 'star-test', path, type, href }])
        const remove = jest.fn(() => [204])
        useMocks({
            post: { '/api/environments/:team_id/file_system_shortcut/': create },
            delete: { '/api/environments/:team_id/file_system_shortcut/star-test/': remove },
        })
        const { getByLabelText } = render(<NavProductRow item={{ path, type, href }} />)
        await waitFor(() => expect(projectTreeDataLogic.values.shortcutDataLoading).toBe(false))
        const initialPath = router.values.location.pathname
        const add = getByLabelText('Add to starred')
        fireEvent.click(add)
        fireEvent.click(add)
        await waitFor(() => expect(projectTreeDataLogic.values.shortcutData).toHaveLength(1))
        expect(create).toHaveBeenCalledTimes(1)
        fireEvent.click(getByLabelText('Remove from starred'))
        const confirm = await waitFor(() => {
            const button = document.querySelector<HTMLButtonElement>('[data-attr="nav-apps-unstar-confirm"]')
            expect(button).not.toBeNull()
            return button!
        })
        expect(remove).not.toHaveBeenCalled()
        fireEvent.click(confirm)
        await waitFor(() => expect(projectTreeDataLogic.values.shortcutData).toHaveLength(0))
        expect(remove).toHaveBeenCalledTimes(1)
        expect(getByLabelText('Add to starred')).toBeTruthy()
        expect(router.values.location.pathname).toBe(initialPath)
    })

    it('offers customize on the pinned Home row and no star on any pinned row', () => {
        navProductsTabLogic.mount()
        const activity = render(
            <NavProductRow item={{ path: 'Activity', iconType: 'activity', href: '/activity/events' }} pinned />
        )
        expect(activity.queryByLabelText('Add to starred')).toBeNull()
        expect(activity.queryByLabelText('Customize sidebar')).toBeNull()
        activity.unmount()

        const home = render(<NavProductRow item={{ path: 'Home', iconType: 'home', href: '/' }} pinned />)
        expect(home.queryByLabelText('Add to starred')).toBeNull()
        fireEvent.click(home.getByLabelText('Customize sidebar'))
        expect(navProductsTabLogic.values.customizeSidebarOpen).toBe(true)
    })
})
