import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { licenseLogic } from './licenseLogic'
import { useMocks } from '~/mocks/jest'
import { LicensePlan, LicenseType } from '~/types'

describe('licenseLogic', () => {
    let logic: ReturnType<typeof licenseLogic.build>

    beforeEach(async () => {
        initKeaTests()
    })

    describe('relevantLicense', () => {
        it('is the top license if there are multiple active ones', async () => {
            useMocks({
                get: {
                    '/api/license/': {
                        count: 4,
                        next: null,
                        previous: null,
                        results: [
                            // Higher plan, expired
                            {
                                id: 1,
                                key: 'tuv',
                                plan: LicensePlan.Enterprise,
                                valid_until: '2022-03-29T12:00:00.000Z',
                                max_users: null,
                                created_at: '2022-03-28T12:00:00.000Z',
                            },
                            // Lower plan, valid
                            {
                                id: 2,
                                key: 'xyz',
                                plan: LicensePlan.Scale,
                                valid_until: '2077-04-28T12:00:00.000Z',
                                max_users: null,
                                created_at: '2022-03-28T12:00:00.000Z',
                            },
                            // Higher plan, valid - DING DING
                            {
                                id: 3,
                                key: 'abc',
                                plan: LicensePlan.Enterprise,
                                valid_until: '2078-04-28T12:00:00.000Z',
                                max_users: null,
                                created_at: '2022-04-28T12:00:00.000Z',
                            },
                            // Lower plan, valid - DING DING
                            {
                                id: 4,
                                key: 'klm',
                                plan: LicensePlan.Scale,
                                valid_until: '2081-04-29T12:00:00.000Z',
                                max_users: null,
                                created_at: '2022-04-25T12:00:00.000Z',
                            },
                        ] as LicenseType[],
                    },
                },
            })
            logic = licenseLogic()
            logic.mount()
            await expectLogic(licenseLogic)
                .toFinishAllListeners()
                .toMatchValues({
                    relevantLicense: {
                        id: 3,
                        key: 'abc',
                        plan: LicensePlan.Enterprise,
                        valid_until: '2078-04-28T12:00:00.000Z',
                        max_users: null,
                        created_at: '2022-04-28T12:00:00.000Z',
                    },
                })
        })

        it('is the most recently expired license if all licenses are expired', async () => {
            useMocks({
                get: {
                    '/api/license/': {
                        count: 3,
                        next: null,
                        previous: null,
                        results: [
                            // Lower plan, expired 1st
                            {
                                id: 1,
                                key: 'abc',
                                plan: LicensePlan.Scale,
                                valid_until: '2022-03-28T12:00:00.000Z',
                                max_users: null,
                                created_at: '2022-02-26T12:00:00.000Z',
                            },
                            // Lower plan, expired 3rd - DING DING
                            {
                                id: 2,
                                key: 'abc',
                                plan: LicensePlan.Scale,
                                valid_until: '2022-03-30T12:00:00.000Z',
                                max_users: null,
                                created_at: '2022-02-27T12:00:00.000Z',
                            },
                            // Higher plan, expired 2nd
                            {
                                id: 3,
                                key: 'def',
                                plan: LicensePlan.Enterprise,
                                valid_until: '2022-03-29T12:00:00.000Z',
                                max_users: null,
                                created_at: '2022-03-28T12:00:00.000Z',
                            },
                        ] as LicenseType[],
                    },
                },
            })
            logic = licenseLogic()
            logic.mount()
            await expectLogic(licenseLogic)
                .toFinishAllListeners()
                .toMatchValues({
                    relevantLicense: {
                        id: 2,
                        key: 'abc',
                        plan: LicensePlan.Scale,
                        valid_until: '2022-03-30T12:00:00.000Z',
                        max_users: null,
                        created_at: '2022-02-27T12:00:00.000Z',
                    },
                })
        })

        it('is null if there are no licenses', async () => {
            useMocks({
                get: {
                    '/api/license/': {
                        count: 0,
                        next: null,
                        previous: null,
                        results: [] as LicenseType[],
                    },
                },
            })
            logic = licenseLogic()
            logic.mount()
            await expectLogic(licenseLogic).toFinishAllListeners().toMatchValues({
                relevantLicense: null,
            })
        })
    })
})
