import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    desktopBetaTermsCreate,
    desktopBetaTermsList,
    desktopBetaTermsRevoke,
} from 'products/tasks/frontend/generated/api'

import { desktopBetaTermsLogic } from './desktopBetaTermsLogic'

jest.mock('products/tasks/frontend/generated/api', () => ({
    desktopBetaTermsCreate: jest.fn(),
    desktopBetaTermsList: jest.fn(),
    desktopBetaTermsRevoke: jest.fn(),
}))

describe('desktopBetaTermsLogic', () => {
    const projectId = String(MOCK_DEFAULT_PROJECT.id)
    let logic: ReturnType<typeof desktopBetaTermsLogic.build>

    beforeEach(() => {
        initKeaTests(true, undefined, undefined, MOCK_DEFAULT_ORGANIZATION)
        jest.mocked(desktopBetaTermsList).mockResolvedValue({ is_desktop_beta_terms_accepted: false })
        jest.mocked(desktopBetaTermsCreate).mockResolvedValue({ is_desktop_beta_terms_accepted: true })
        jest.mocked(desktopBetaTermsRevoke).mockResolvedValue({ is_desktop_beta_terms_accepted: false })
        logic = desktopBetaTermsLogic({ projectId })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads, accepts, and withdraws the beta terms through the current project', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadDesktopBetaTermsAcceptedSuccess'])
            .toMatchValues({ desktopBetaTermsAccepted: false })

        logic.actions.acceptDesktopBetaTerms()

        await expectLogic(logic)
            .toDispatchActions(['acceptDesktopBetaTermsSuccess'])
            .toMatchValues({ desktopBetaTermsAccepted: true })

        expect(desktopBetaTermsList).toHaveBeenCalledTimes(1)
        expect(desktopBetaTermsList).toHaveBeenCalledWith(projectId)
        expect(desktopBetaTermsList).not.toHaveBeenCalledWith(MOCK_DEFAULT_ORGANIZATION.id)
        expect(desktopBetaTermsCreate).toHaveBeenCalledTimes(1)
        expect(desktopBetaTermsCreate).toHaveBeenCalledWith(projectId)
        expect(desktopBetaTermsCreate).not.toHaveBeenCalledWith(MOCK_DEFAULT_ORGANIZATION.id)

        logic.actions.revokeDesktopBetaTerms()

        await expectLogic(logic)
            .toDispatchActions(['revokeDesktopBetaTermsSuccess'])
            .toMatchValues({ desktopBetaTermsAccepted: false })

        expect(desktopBetaTermsRevoke).toHaveBeenCalledTimes(1)
        expect(desktopBetaTermsRevoke).toHaveBeenCalledWith(projectId)
        expect(desktopBetaTermsRevoke).not.toHaveBeenCalledWith(MOCK_DEFAULT_ORGANIZATION.id)
    })
})
