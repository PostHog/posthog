import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { urls } from 'scenes/urls'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { preflightLogic } from './preflightLogic'

describe('preflightLogic', () => {
    let logic: ReturnType<typeof preflightLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '_preflight/': {
                    django: false,
                    redis: false,
                    plugins: false,
                    celery: false,
                    clickhouse: false,
                    kafka: false,
                    db: false,
                    initiated: false,
                    cloud: false,
                    demo: false,
                    realm: 'hosted-clickhouse',
                    available_social_auth_providers: {
                        github: false,
                        gitlab: false,
                        'google-oauth2': false,
                    },
                    can_create_org: true,
                    email_service_available: false,
                },
            },
        })
        initKeaTests()
        logic = preflightLogic()
        logic.mount()
    })

    it('loads preflight data onMount', async () => {
        await expectLogic(logic).toDispatchActions(['loadPreflight', 'loadPreflightSuccess'])
    })

    describe('preflight mode', () => {
        it('is updated by changing urls', async () => {
            await expectLogic(logic, () => {
                router.actions.push(urls.preflight(), { mode: 'live' })
            })
                .toDispatchActions(['setPreflightMode'])
                .toMatchValues({ preflightMode: 'live' })
        })

        it('changing it updates the url', async () => {
            logic.actions.setPreflightMode('live')
            expect(router.values.searchParams).toHaveProperty('mode', 'live')
        })
    })
})
