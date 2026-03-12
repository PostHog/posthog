import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { TrendsQuery } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { HARNESS_INSIGHT_ID } from './InsightHarness'

const DEBOUNCE_TIMEOUT = 3000

function getLogic(): ReturnType<typeof insightVizDataLogic.build> {
    const props: InsightLogicProps = { dashboardItemId: HARNESS_INSIGHT_ID }
    return insightVizDataLogic(props)
}

async function clickSelect(dataAttr: string, optionText: string | RegExp): Promise<void> {
    const trigger = screen.getByTestId(dataAttr)
    await userEvent.click(trigger)
    const name = typeof optionText === 'string' ? new RegExp(`^${optionText}`) : optionText
    const options = screen.getAllByRole('menuitem', { name })
    await userEvent.click(options[0])
}

async function searchAndSelect(triggerAttr: string, searchText: string, resultAttr: string): Promise<void> {
    await userEvent.click(screen.getByTestId(triggerAttr))

    const searchInput = await screen.findByTestId('taxonomic-filter-searchfield')
    await userEvent.clear(searchInput)
    await userEvent.type(searchInput, searchText)

    await waitFor(
        () => {
            const el = screen.getByTestId(resultAttr)
            expect(el.textContent).toContain(searchText)
        },
        { timeout: DEBOUNCE_TIMEOUT }
    )

    await userEvent.click(screen.getByTestId(resultAttr))
}

export const series = {
    async select(index: number, eventName: string): Promise<void> {
        await searchAndSelect(`trend-element-subject-${index}`, eventName, 'prop-filter-events-0')

        await waitFor(() => expect(getQuerySource().series[index].event).toBe(eventName), { timeout: DEBOUNCE_TIMEOUT })
    },

    async add(eventName: string): Promise<void> {
        const before = getQuerySource().series.length
        await searchAndSelect('add-action-event-button', eventName, 'prop-filter-events-0')

        await waitFor(
            () => {
                const src = getQuerySource()
                expect(src.series).toHaveLength(before + 1)
                expect(src.series[before].event).toBe(eventName)
            },
            { timeout: DEBOUNCE_TIMEOUT }
        )
    },
}

export const breakdown = {
    async set(propertyName: string): Promise<void> {
        await searchAndSelect('add-breakdown-button', propertyName, 'prop-filter-event_properties-0')

        await waitFor(
            () => {
                const bf = getQuerySource().breakdownFilter
                expect(bf?.breakdowns?.[0]?.property ?? bf?.breakdown).toBe(propertyName)
            },
            { timeout: DEBOUNCE_TIMEOUT }
        )
    },
}

export const interval = {
    async set(value: 'minute' | 'hour' | 'day' | 'week' | 'month'): Promise<void> {
        await clickSelect('interval-filter', value)

        await waitFor(() => expect(getQuerySource().interval).toBe(value), { timeout: DEBOUNCE_TIMEOUT })
    },
}

export const display = {
    async set(optionText: string): Promise<void> {
        await clickSelect('chart-filter', optionText)

        await waitFor(() => expect(getQuerySource().trendsFilter?.display).toBeTruthy(), { timeout: DEBOUNCE_TIMEOUT })
    },
}

export const compare = {
    async enable(): Promise<void> {
        await clickSelect('compare-filter', 'Compare to previous period')

        await waitFor(() => expect(getQuerySource().compareFilter?.compare).toBe(true), { timeout: DEBOUNCE_TIMEOUT })
    },

    async disable(): Promise<void> {
        await clickSelect('compare-filter', 'No comparison')

        await waitFor(() => expect(getQuerySource().compareFilter?.compare).toBeFalsy(), { timeout: DEBOUNCE_TIMEOUT })
    },
}

export function getQuerySource(): TrendsQuery {
    return getLogic().values.querySource as TrendsQuery
}
