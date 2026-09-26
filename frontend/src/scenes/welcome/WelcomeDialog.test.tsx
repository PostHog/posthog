import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { cleanup, render } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { type ReactNode } from 'react'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, type AppContext } from '~/types'

import { MaybeWelcomeDialog } from './WelcomeDialog'

jest.mock('posthog-js')
jest.mock('lib/lemon-ui/LemonModal', () => ({
    LemonModal: ({ children, 'data-attr': dataAttr }: { children: ReactNode; 'data-attr'?: string }) => (
        <div data-attr={dataAttr}>{children}</div>
    ),
}))

const Component = (): JSX.Element => <div />
const testScenes: Record<string, () => any> = {
    [Scene.ProjectHomepage]: () => ({ scene: { component: Component } }),
}

describe('MaybeWelcomeDialog', () => {
    afterEach(cleanup)

    test.each([
        ['available', AccessControlLevel.Member, Scene.ProjectHomepage, true],
        ['unavailable', AccessControlLevel.None, Scene.ErrorProjectUnavailable, false],
    ])(
        'on the home of an %s project renders the dialog: %s',
        async (_, userAccessLevel, expectedActiveScene, rendered) => {
            window.localStorage.clear()
            window.sessionStorage.clear()
            const currentTeam = { ...MOCK_DEFAULT_TEAM, user_access_level: userAccessLevel }
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT,
                current_user: { ...MOCK_DEFAULT_USER, is_organization_first_user: false },
            } as AppContext
            useMocks({
                get: {
                    '/api/environments/@current/': currentTeam,
                    '/api/projects/@current/': currentTeam,
                    '/api/organizations/@current/welcome/current/': { organization_name: 'MockHog' },
                },
            })
            initKeaTests(true, currentTeam)
            await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
            userLogic.mount()
            router.actions.push(urls.projectHomepage())
            const logic = sceneLogic.build({ scenes: testScenes })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['setScene'])
                .toMatchValues({ sceneId: Scene.ProjectHomepage, activeSceneId: expectedActiveScene })

            render(<MaybeWelcomeDialog />)

            expect(document.querySelector('[data-attr="welcome-dialog"]') !== null).toBe(rendered)
        }
    )
})
