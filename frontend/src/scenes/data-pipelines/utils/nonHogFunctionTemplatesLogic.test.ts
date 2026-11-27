import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'
import { PreflightStatus } from '~/types'

import { nonHogFunctionTemplatesLogic } from './nonHogFunctionTemplatesLogic'

describe('nonHogFunctionTemplatesLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        ['offers batch export templates by default', {}, true],
        ['offers none on an instance that runs no batch exports', { batch_exports_enabled: false }, false],
    ])('%s', async (_, preflight, expectTemplates) => {
        preflightLogic.mount()
        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        preflightLogic.actions.loadPreflightSuccess({
            ...preflightLogic.values.preflight,
            ...preflight,
        } as PreflightStatus)
        const logic = nonHogFunctionTemplatesLogic({ availableSources: {} })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.hogFunctionTemplatesBatchExports.length > 0).toBe(expectTemplates)
    })
})
