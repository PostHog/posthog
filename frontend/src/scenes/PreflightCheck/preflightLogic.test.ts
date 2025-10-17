import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { preflightLogic } from './preflightLogic'

describe('preflightLogic', () => {
    let logic: ReturnType<typeof preflightLogic.build>

    beforeEach(() => {
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

    describe('checks', () => {
        it('parses checks correctly for live mode', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setPreflightMode('live')
            })
                .toDispatchActions(['loadPreflightSuccess'])
                .toMatchValues({
                    checks: [
                        {
                            id: 'database',
                            name: 'Application database · Postgres',
                            status: 'validated',
                        },
                        {
                            id: 'clickhouse',
                            name: 'Analytics database · ClickHouse',
                            status: 'validated',
                        },
                        {
                            id: 'kafka',
                            name: 'Queue · Kafka',
                            status: 'validated',
                        },
                        {
                            id: 'backend',
                            name: 'Backend server · Django',
                            status: 'validated',
                        },
                        {
                            id: 'redis',
                            name: 'Cache · Redis',
                            status: 'validated',
                        },
                        {
                            id: 'celery',
                            name: 'Background jobs · Celery',
                            status: 'error',
                        },
                        {
                            id: 'plugins',
                            name: 'Plugin server · Node',
                            status: 'error',
                        },
                        {
                            id: 'frontend',
                            name: 'Frontend build · Webpack',
                            status: 'validated',
                        },
                        {
                            id: 'tls',
                            name: 'SSL/TLS certificate',
                            status: 'warning',
                            caption: 'Set up before ingesting real user data',
                        },
                        {
                            id: 'object_storage',
                            name: 'Object Storage',
                            status: 'validated',
                        },
                    ],
                })
        })

        it('parses checks correctly for experimentation mode', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setPreflightMode('experimentation')
            })
                .toDispatchActions(['loadPreflightSuccess'])
                .toMatchValues({
                    checks: [
                        {
                            id: 'database',
                            name: 'Application database · Postgres',
                            status: 'validated',
                        },
                        {
                            id: 'clickhouse',
                            name: 'Analytics database · ClickHouse',
                            status: 'validated',
                        },
                        {
                            id: 'kafka',
                            name: 'Queue · Kafka',
                            status: 'validated',
                        },
                        {
                            id: 'backend',
                            name: 'Backend server · Django',
                            status: 'validated',
                        },
                        {
                            id: 'redis',
                            name: 'Cache · Redis',
                            status: 'validated',
                        },
                        {
                            id: 'celery',
                            name: 'Background jobs · Celery',
                            status: 'warning',
                            caption: 'Required in production environments',
                        },
                        {
                            id: 'plugins',
                            name: 'Plugin server · Node',
                            status: 'warning',
                            caption: 'Required in production environments',
                        },
                        {
                            id: 'frontend',
                            name: 'Frontend build · Webpack',
                            status: 'validated',
                        },
                        {
                            id: 'tls',
                            name: 'SSL/TLS certificate',
                            status: 'optional',
                            caption: 'Not required for experimentation mode',
                        },
                        {
                            id: 'object_storage',
                            name: 'Object Storage',
                            status: 'validated',
                        },
                    ],
                })
        })
    })
    describe('check summaries', () => {
        it('creates check summaries correctly for live mode', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setPreflightMode('live')
            })
                .toDispatchActions(['loadPreflightSuccess'])
                .toMatchValues({
                    checksSummary: {
                        summaryString: '7 successful, 1 warning, 2 errors',
                        summaryStatus: 'error',
                    },
                })
        })

        it('creates check summaries correctly for experimentation mode', async () => {
            await expectLogic(logic, async () => {
                logic.actions.setPreflightMode('experimentation')
            })
                .toDispatchActions(['loadPreflightSuccess'])
                .toMatchValues({
                    checksSummary: {
                        summaryString: '7 successful, 2 warnings, 1 optional',
                        summaryStatus: 'warning',
                    },
                })
        })
    })
})
