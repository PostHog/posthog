import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { desktopBetaTermsCreate, desktopBetaTermsList } from 'products/tasks/frontend/generated/api'

import { desktopBetaTermsLogic } from './desktopBetaTermsLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    desktopBetaTermsCreate: jest.fn(),
    desktopBetaTermsList: jest.fn(),
}))

describe('desktopBetaTermsLogic', () => {
    const organizationId = MOCK_DEFAULT_ORGANIZATION.id
    let logic: ReturnType<typeof desktopBetaTermsLogic.build>

    beforeEach(() => {
        initKeaTests(true, undefined, undefined, MOCK_DEFAULT_ORGANIZATION)
        jest.mocked(desktopBetaTermsList).mockResolvedValue({ is_desktop_beta_terms_accepted: false })
        jest.mocked(desktopBetaTermsCreate).mockResolvedValue({ is_desktop_beta_terms_accepted: true })
        logic = desktopBetaTermsLogic({ organizationId })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads and accepts the beta terms for the current organization', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadDesktopBetaTermsAcceptedSuccess'])
            .toMatchValues({ desktopBetaTermsAccepted: false })

        logic.actions.acceptDesktopBetaTerms()

        await expectLogic(logic)
            .toDispatchActions(['acceptDesktopBetaTermsSuccess'])
            .toMatchValues({ desktopBetaTermsAccepted: true })

        expect(desktopBetaTermsList).toHaveBeenCalledTimes(1)
        expect(desktopBetaTermsList).toHaveBeenCalledWith(organizationId)
        expect(desktopBetaTermsCreate).toHaveBeenCalledTimes(1)
        expect(desktopBetaTermsCreate).toHaveBeenCalledWith(organizationId)
    })
})
