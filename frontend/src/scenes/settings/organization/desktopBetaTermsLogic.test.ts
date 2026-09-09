import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { desktopBetaTermsCreate, desktopBetaTermsList } from 'products/tasks/frontend/generated/api'

import { desktopBetaTermsLogic } from './desktopBetaTermsLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    desktopBetaTermsCreate: jest.fn(),
    desktopBetaTermsList: jest.fn(),
}))

describe('desktopBetaTermsLogic', () => {
    const projectId = String(MOCK_DEFAULT_PROJECT.id)
    let logic: ReturnType<typeof desktopBetaTermsLogic.build>

    beforeEach(() => {
        initKeaTests(true, undefined, undefined, MOCK_DEFAULT_ORGANIZATION)
        jest.mocked(desktopBetaTermsList).mockResolvedValue({ is_desktop_beta_terms_accepted: false })
        jest.mocked(desktopBetaTermsCreate).mockResolvedValue({ is_desktop_beta_terms_accepted: true })
        logic = desktopBetaTermsLogic({ projectId })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads and accepts the beta terms through the current project', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadDesktopBetaTermsAcceptedSuccess'])
            .toMatchValues({ desktopBetaTermsAccepted: false })

        logic.actions.acceptDesktopBetaTerms()

        await expectLogic(logic)
            .toDispatchActions(['acceptDesktopBetaTermsSuccess'])
            .toMatchValues({ desktopBetaTermsAccepted: true })

        expect(desktopBetaTermsList).toHaveBeenCalledTimes(1)
        expect(desktopBetaTermsList).toHaveBeenCalledWith(projectId)
        expect(desktopBetaTermsCreate).toHaveBeenCalledTimes(1)
        expect(desktopBetaTermsCreate).toHaveBeenCalledWith(projectId)
    })
})
