import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
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
        expect(getByLabelText('Add to starred').getAttribute('aria-disabled')).toBe('true')
    })

    it.each([
        ['Feature flags', 'feature_flag', '/feature_flags', false],
        ['Home', 'home', '/', true],
    ])('adds and removes a star for %s through the shortcut API', async (path, type, href, hasMenu) => {
        const create = jest.fn(() => [201, { id: 'star-test', path, type, href }])
        const remove = jest.fn(() => [204])
        useMocks({
            post: { '/api/environments/:team_id/file_system_shortcut/': create },
            delete: { '/api/environments/:team_id/file_system_shortcut/star-test/': remove },
        })
        const { getByLabelText, queryByLabelText, findByText } = render(<NavAppRow item={{ path, type, href }} />)
        await waitFor(() => expect(projectTreeDataLogic.values.shortcutDataLoading).toBe(false))
        const initialPath = router.values.location.pathname
        const starButton = async (name: string): Promise<HTMLElement> => {
            if (hasMenu) {
                fireEvent.click(getByLabelText(`Open ${path} menu`))
                expect(await findByText('Configure home')).toBeTruthy()
                return await findByText(name)
            }
            expect(queryByLabelText(`Open ${path} menu`)).toBeNull()
            return getByLabelText(name)
        }
        const add = await starButton('Add to starred')
        fireEvent.click(add)
        fireEvent.click(add)
        await waitFor(() => expect(projectTreeDataLogic.values.shortcutData).toHaveLength(1))
        expect(create).toHaveBeenCalledTimes(1)
        const removeButton = await starButton('Remove from starred')
        fireEvent.click(removeButton)
        fireEvent.click(removeButton)
        await waitFor(() => expect(projectTreeDataLogic.values.shortcutData).toHaveLength(0))
        expect(remove).toHaveBeenCalledTimes(1)
        expect(await starButton('Add to starred')).toBeTruthy()
        expect(router.values.location.pathname).toBe(initialPath)
    })

    it('does not treat a file shortcut with the same name as a starred app', async () => {
        const fileShortcut = {
            id: 'file-star',
            path: 'Feature flags',
            type: 'insight',
            ref: 'insight-1',
            href: '/insights/insight-1',
        }
        const appShortcut = { id: 'app-star', path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' }
        const create = jest.fn(() => [201, appShortcut])
        const removeFile = jest.fn(() => [204])
        useMocks({
            post: { '/api/environments/:team_id/file_system_shortcut/': create },
            delete: { '/api/environments/:team_id/file_system_shortcut/file-star/': removeFile },
        })
        const { getByLabelText } = render(
            <NavAppRow item={{ path: 'Feature flags', type: 'feature_flag', href: '/feature_flags' }} />
        )
        await waitFor(() => expect(projectTreeDataLogic.values.shortcutDataLoading).toBe(false))
        act(() => projectTreeDataLogic.actions.loadShortcutsSuccess([fileShortcut]))
        expect(projectTreeDataLogic.values.shortcutData).toEqual([fileShortcut])

        fireEvent.click(getByLabelText('Add to starred'))

        await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
        expect(removeFile).not.toHaveBeenCalled()
        expect(projectTreeDataLogic.values.shortcutData).toEqual([fileShortcut, appShortcut])
    })
})
