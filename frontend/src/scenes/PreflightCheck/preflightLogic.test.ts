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
                            status: 'running',
                        },
                        {
                            id: 'clickhouse',
                            name: 'Analytics database · ClickHouse',
                            status: 'running',
                        },
                        {
                            id: 'kafka',
                            name: 'Queue · Kafka',
                            status: 'running',
                        },
                        {
                            id: 'backend',
                            name: 'Backend server · Django',
                            status: 'running',
                        },
                        {
                            id: 'redis',
                            name: 'Cache · Redis',
                            status: 'running',
                        },
                        {
                            id: 'celery',
                            name: 'Background jobs · Celery',
                            status: 'down',
                        },
                        {
                            id: 'plugins',
                            name: 'Plugin server · Node',
                            status: 'down',
                        },
                        {
                            id: 'frontend',
                            name: 'Frontend build · Webpack',
                            status: 'running',
                        },
                        {
                            id: 'tls',
                            name: 'SSL/TLS certificate',
                            status: 'warning',
                            caption: 'Set up before ingesting real user data',
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
                            status: 'running',
                        },
                        {
                            id: 'clickhouse',
                            name: 'Analytics database · ClickHouse',
                            status: 'running',
                        },
                        {
                            id: 'kafka',
                            name: 'Queue · Kafka',
                            status: 'running',
                        },
                        {
                            id: 'backend',
                            name: 'Backend server · Django',
                            status: 'running',
                        },
                        {
                            id: 'redis',
                            name: 'Cache · Redis',
                            status: 'running',
                        },
                        {
                            id: 'celery',
                            name: 'Background jobs · Celery',
                            status: 'down',
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
                            status: 'running',
                        },
                        {
                            id: 'tls',
                            name: 'SSL/TLS certificate',
                            status: 'optional',
                            caption: 'Not required for experimentation mode',
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
                        summaryString: '6 successful, 1 warning, 2 errors',
                        summaryStatus: 'down',
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
                        summaryString: '6 successful, 1 warning, 1 error, 1 optional',
                        summaryStatus: 'down',
                    },
                })
        })
    })
})
