import { expectLogic } from 'kea-test-utils'

import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { renameModalLogic } from 'scenes/insights/filters/ActionFilter/renameModalLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { getDisplayNameFromEntityNode } from 'scenes/insights/utils'

import { initKeaTests } from '~/test/init'

import filtersJson from './__mocks__/filters.json'
import { legacyFiltersToSeries } from './legacyFilters'

const series = legacyFiltersToSeries(filtersJson as any)

describe('renameModalLogic', () => {
    let logic: ReturnType<typeof renameModalLogic.build>
    let relevantEntityFilterLogic: ReturnType<typeof entityFilterLogic.build>
    let someInsightDataLogic: ReturnType<typeof insightDataLogic.build>

    beforeEach(() => {
        initKeaTests()
        someInsightDataLogic = insightDataLogic({ dashboardItemId: 'new' })
        someInsightDataLogic.mount()
        relevantEntityFilterLogic = entityFilterLogic({
            onChange: jest.fn(),
            series,
            typeKey: 'new',
        })
        relevantEntityFilterLogic.mount()
        logic = renameModalLogic({
            node: series[0],
            typeKey: 'new',
        })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([relevantEntityFilterLogic])
        })

        it('name', async () => {
            await expectLogic(logic).toMatchValues({
                name: getDisplayNameFromEntityNode(series[0]),
            })
        })
    })

    describe('modifying name', () => {
        it('set name', () => {
            expectLogic(logic, () => {
                logic.actions.setName('veggie_straws')
            })
                .toDispatchActions(['setName'])
                .toMatchValues({ name: 'veggie_straws' })
        })

        it('follows the selected series', async () => {
            await expectLogic(relevantEntityFilterLogic, () => {
                relevantEntityFilterLogic.actions.selectSeries(0, {
                    ...series[0],
                    custom_name: 'zesty_veggie_straws',
                })
            }).toDispatchActions(['selectSeries'])

            await expectLogic(logic).toMatchValues({
                name: 'zesty_veggie_straws',
            })
        })

        it('selects the series the results table picks by index', async () => {
            await expectLogic(relevantEntityFilterLogic, () => {
                relevantEntityFilterLogic.actions.selectSeriesAt(2)
            }).toDispatchActions(['selectSeriesAt', 'selectSeries'])

            await expectLogic(logic).toMatchValues({
                name: 'Users signed up',
            })
        })
    })
})
