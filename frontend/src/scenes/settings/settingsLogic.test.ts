import { expectLogic } from 'kea-test-utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { settingsLogic } from './settingsLogic'

describe('settingsLogic', () => {
    // Managed reverse proxy needs proxy infrastructure that only PostHog Cloud runs, so a
    // self-hosted instance must not be offered the section at all.
    it.each([
        ['hides', false],
        ['shows', true],
    ])('%s managed reverse proxy when cloud is %s', async (_name, cloud) => {
        // The fixture is a debug build, and isCloudOrDev accepts is_debug on its own.
        useMocks({ get: { '/_preflight': [200, { ...preflightJson, cloud, is_debug: false }] } })
        initKeaTests()

        const logic = settingsLogic()
        logic.mount()

        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])

        expect(logic.values.sections.some((section) => section.id === 'organization-proxy')).toBe(cloud)
    })
})
