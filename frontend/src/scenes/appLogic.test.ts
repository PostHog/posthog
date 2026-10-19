import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { userLogic } from 'scenes/userLogic'

import preflightJson from '~/mocks/fixtures/_preflight.json'
import { initKeaTests } from '~/test/init'
import { AppContext, PreflightStatus } from '~/types'

describe('appLogic', () => {
    afterEach(() => {
        window.POSTHOG_APP_CONTEXT = undefined
    })

    it.each([
        { page: '/login', loggedIn: false, flagsArrived: false, timedOut: false, showApp: true },
        { page: '/signup', loggedIn: false, flagsArrived: false, timedOut: false, showApp: false },
        { page: '/signup', loggedIn: false, flagsArrived: true, timedOut: false, showApp: true },
        { page: '/signup', loggedIn: false, flagsArrived: false, timedOut: true, showApp: true },
        { page: '/login', loggedIn: true, flagsArrived: false, timedOut: false, showApp: false },
        { page: '/login', loggedIn: true, flagsArrived: true, timedOut: false, showApp: true },
        {
            fromPage: '/login',
            page: '/signup',
            loggedIn: false,
            flagsArrived: false,
            timedOut: false,
            showApp: false,
        },
        {
            fromPage: '/signup',
            page: '/login',
            loggedIn: false,
            flagsArrived: false,
            timedOut: false,
            showApp: true,
        },
    ])(
        '$page loggedIn=$loggedIn flagsArrived=$flagsArrived timedOut=$timedOut shows=$showApp',
        ({ page, fromPage, loggedIn, flagsArrived, timedOut, showApp }) => {
            window.POSTHOG_APP_CONTEXT = {
                current_user: loggedIn ? MOCK_DEFAULT_USER : null,
                preflight: {
                    ...preflightJson,
                    slack_service: { available: false },
                    data_warehouse_integrations: { hubspot: {}, salesforce: {} },
                    wizard_cloud_run_available: false,
                } as PreflightStatus,
            } as AppContext
            initKeaTests()
            router.actions.push(fromPage ?? page)
            userLogic.mount()
            appLogic.mount()
            if (fromPage) {
                router.actions.push(page)
            }
            if (flagsArrived) {
                featureFlagLogic.actions.setFeatureFlags([], {})
            }
            if (timedOut) {
                appLogic.actions.ignoreFeatureFlags()
            }

            expect(!!appLogic.values.showApp).toBe(showApp)
        }
    )
})
