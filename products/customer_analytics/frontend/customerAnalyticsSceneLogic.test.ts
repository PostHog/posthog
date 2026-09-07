import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { sceneLogic } from 'scenes/sceneLogic'
import { emptySceneParams } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NodeKind, RetentionFilter, RetentionQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

describe('customerAnalyticsSceneLogic', () => {
    let logic: ReturnType<typeof customerAnalyticsSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        sceneLogic.mount()
        router.actions.push(urls.customerAnalytics())
        logic = customerAnalyticsSceneLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        localStorage.clear()
    })

    describe('filterTestAccounts', () => {
        it('defaults to true', () => {
            expectLogic(logic).toMatchValues({
                filterTestAccounts: true,
            })
        })

        it('can be toggled off', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilterTestAccounts(false)
            }).toMatchValues({
                filterTestAccounts: false,
            })
        })

        it('can be toggled on', async () => {
            logic.actions.setFilterTestAccounts(false)

            await expectLogic(logic, () => {
                logic.actions.setFilterTestAccounts(true)
            }).toMatchValues({
                filterTestAccounts: true,
            })
        })
    })

    describe('retentionInsights', () => {
        const retentionFilters = (): RetentionFilter[] =>
            customerAnalyticsSceneLogic
                .findMounted()!
                .values.retentionInsights.map((insight) => (insight.query.source as RetentionQuery).retentionFilter)

        it('builds daily and weekly retention on the configured activity event', () => {
            expect(retentionFilters()).toEqual([
                expect.objectContaining({
                    period: 'Day',
                    totalIntervals: 8,
                    targetEntity: { type: 'events', id: '$pageview', name: '$pageview' },
                }),
                expect.objectContaining({
                    period: 'Week',
                    totalIntervals: 5,
                    targetEntity: { type: 'events', id: '$pageview', name: '$pageview' },
                }),
            ])
        })

        it('aggregates on the selected group type for b2b', () => {
            logic.actions.setBusinessType('b2b')
            logic.actions.setSelectedGroupType(1)

            for (const insight of logic.values.retentionInsights) {
                expect(insight.query.source).toMatchObject({ aggregation_group_type_index: 1 })
            }
        })
    })

    describe('period comparison', () => {
        it('is on for every signup and session tile whose query kind supports it', () => {
            // Lifecycle is the one overview query kind with no compareFilter in the schema.
            const tiles = [...logic.values.signupInsights, ...logic.values.sessionInsights].filter(
                (insight) => insight.query.source.kind !== NodeKind.LifecycleQuery
            )

            expect(tiles.length).toBeGreaterThan(0)
            expect(
                tiles
                    .filter(
                        (insight) =>
                            !('compareFilter' in insight.query.source) || !insight.query.source.compareFilter?.compare
                    )
                    .map((insight) => insight.name)
            ).toEqual([])
        })

        it('is off for every signup tile on the all time range', () => {
            logic.actions.setDates('all', null)

            expect(
                logic.values.signupInsights
                    .filter((insight) => 'compareFilter' in insight.query.source)
                    .map((insight) => insight.name)
            ).toEqual([])
        })
    })

    describe('URL sync', () => {
        it('activates the Requests tab for its scene key', () => {
            sceneLogic.actions.setScene(Scene.CustomerAnalytics, 'customerAnalyticsFeatureRequests', emptySceneParams)

            expectLogic(logic).toMatchValues({ activeTab: 'feature_requests' })
        })

        it('activates the Tasks tab for its scene key', () => {
            sceneLogic.actions.setScene(Scene.CustomerAnalytics, 'customerAnalyticsTasks', emptySceneParams)

            expectLogic(logic).toMatchValues({ activeTab: 'tasks' })
        })

        it('activates the Accounts tab for the account detail scene key', () => {
            sceneLogic.actions.setScene(Scene.CustomerAnalyticsAccount, 'customerAnalyticsAccount', emptySceneParams)

            expectLogic(logic).toMatchValues({ activeTab: 'accounts' })
        })

        it('reads filter_test_accounts from URL', () => {
            expectLogic(logic).toMatchValues({
                filterTestAccounts: true,
            })

            router.actions.push(urls.customerAnalytics(), {
                filter_test_accounts: 'false',
            })

            expectLogic(logic).toMatchValues({
                filterTestAccounts: false,
            })
        })
    })
})
