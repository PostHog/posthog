import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { wizardLogic } from './wizardLogic'

const MOCK_HASH = 'mock-hash'

describe('wizardLogic', () => {
    let logic: ReturnType<typeof wizardLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = wizardLogic()
        logic.mount()
    })

    describe('when hash is not present in the URL', () => {
        it('sets view to invalid when no hash is provided in url', async () => {
            router.actions.push('/wizard')

            await expectLogic(logic).toMatchValues({
                view: 'invalid',
                wizardHash: null,
            })
        })
    })

    describe('if more than one project is available', () => {
        beforeEach(() => {
            window.POSTHOG_APP_CONTEXT = {
                current_user: {
                    organization: {
                        teams: [MOCK_DEFAULT_TEAM, { ...MOCK_DEFAULT_TEAM, id: MOCK_DEFAULT_TEAM.id + 1 }],
                    },
                },
            } as unknown as AppContext
            initKeaTests()
            logic = wizardLogic()
            logic.mount()
        })
        it('sets view to project', async () => {
            router.actions.push('/wizard', { hash: MOCK_HASH })
            await expectLogic(logic).toMatchValues({
                view: 'project',
                wizardHash: MOCK_HASH,
            })
        })
    })

    describe('if only one project is available', () => {
        beforeEach(() => {
            window.POSTHOG_APP_CONTEXT = {
                current_user: {
                    organization: {
                        ...MOCK_DEFAULT_ORGANIZATION,
                        teams: [MOCK_DEFAULT_TEAM],
                    },
                },
            } as unknown as AppContext
            initKeaTests()
            logic = wizardLogic()
            logic.mount()
        })

        it('sets view to pending', async () => {
            router.actions.push('/wizard', { hash: MOCK_HASH })
            await expectLogic(logic).toMatchValues({
                view: 'pending',
                wizardHash: MOCK_HASH,
            })
        })
    })

    describe('if wizard authentication call fails', () => {
        it('sets view to invalid when authentication fails', async () => {
            useMocks({
                post: {
                    '/api/wizard/authenticate/': () => [400, { status: 0 }],
                },
            })

            logic.actions.setWizardHash(MOCK_HASH)
            logic.actions.setSelectedProjectId(MOCK_DEFAULT_TEAM.id)
            logic.actions.continueToAuthentication()

            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                view: 'invalid',
            })
        })
    })

    describe('if wizard authentication call succeeds', () => {
        it('sets view to success when authentication succeeds', async () => {
            useMocks({
                post: {
                    '/api/wizard/authenticate/': () => [200, { status: 1 }],
                },
            })

            logic.actions.setWizardHash(MOCK_HASH)
            logic.actions.setSelectedProjectId(MOCK_DEFAULT_TEAM.id)
            logic.actions.continueToAuthentication()

            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                view: 'success',
            })
        })
    })
})
