import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { FileSystemImport } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { todayProductsLogic } from './todayProductsLogic'

const FLAGS = { path: 'Feature flags', href: '/feature_flags', type: 'feature_flag' } as FileSystemImport
const REPLAY = { path: 'Session replay', href: '/replay/home', type: 'session_recording' } as FileSystemImport

describe('todayProductsLogic', () => {
    let capture: jest.SpyInstance

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/file_system_shortcut/': {
                    results: [{ id: 'sc-1', type: 'feature_flag', path: 'Feature flags', href: '/feature_flags' }],
                },
            },
            post: {
                '/api/projects/:team_id/file_system_shortcut/': {
                    id: 'sc-2',
                    type: 'session_recording',
                    path: 'Session replay',
                    href: '/replay/home',
                },
            },
            delete: {
                '/api/projects/:team_id/file_system_shortcut/:id/': {},
            },
        })
        initKeaTests()
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    it('reports star toggles with the state the click moves to', async () => {
        const logic = todayProductsLogic()
        logic.mount()
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])

        // Session replay has no shortcut, so the click stars it. Feature flags has one, so the click unstars it.
        // The guard drops clicks while a change saves, so each toggle settles before the next.
        logic.actions.toggleStarred(REPLAY)
        await expectLogic(projectTreeDataLogic).toFinishAllListeners()
        logic.actions.toggleStarred(FLAGS)

        const toggles = capture.mock.calls
            .filter(([name]) => name === 'today product star toggled')
            .map(([, properties]) => [properties.product, properties.starred])
        expect(toggles).toEqual([
            ['/replay/home', true],
            ['/feature_flags', false],
        ])
    })

    it('reports nothing for a star click that lands while a change saves', async () => {
        const logic = todayProductsLogic()
        logic.mount()
        // Shortcuts are still loading, so the guard drops the click before it reads them.
        logic.actions.toggleStarred(REPLAY)
        expect(capture.mock.calls.filter(([name]) => name === 'today product star toggled')).toEqual([])
    })

    it('reports product opens with the row placement and current starred state', async () => {
        const logic = todayProductsLogic()
        logic.mount()
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])

        logic.actions.productOpened(REPLAY, 'all', 'Behaviour', 3)
        expect(capture).toHaveBeenCalledWith('today product opened', {
            product: '/replay/home',
            section: 'all',
            category: 'Behaviour',
            position: 3,
            starred: logic.values.starredHrefs.has('/replay/home'),
        })
    })
})
