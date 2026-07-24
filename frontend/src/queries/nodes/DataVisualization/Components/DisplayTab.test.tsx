import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DataVisualizationLogicProps, dataVisualizationLogic } from '../dataVisualizationLogic'
import { displayLogic } from '../displayLogic'
import { DisplayTab } from './DisplayTab'

describe('DisplayTab', () => {
    afterEach(() => {
        cleanup()
    })

    it('labels Y-axis tick toggles explicitly', async () => {
        initKeaTests()

        const key = 'display-tab-axis-tick-label-test'
        const query: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select company_size, accounts, revenue from numbers(2)',
            },
            display: ChartDisplayType.ActionsBar,
            chartSettings: {},
        }

        const props: DataVisualizationLogicProps = {
            key,
            query,
            dataNodeCollectionId: key,
            setQuery: jest.fn(),
        }

        dataVisualizationLogic(props).mount()
        displayLogic({ key }).mount()

        render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <BindLogic logic={displayLogic} props={{ key }}>
                    <DisplayTab />
                </BindLogic>
            </BindLogic>
        )

        const user = userEvent.setup()

        await user.click(await screen.findByText('Left Y-axis'))
        await user.click(screen.getByText('Right Y-axis'))

        expect(screen.getByText('Show X-axis tick labels')).toBeInTheDocument()
        expect(screen.getAllByText('Show tick labels')).toHaveLength(2)
        expect(screen.queryByText('Show X-axis labels')).not.toBeInTheDocument()
        expect(screen.queryByText('Show labels')).not.toBeInTheDocument()
    })

    it('persists chart axis labels without dropping existing axis settings', async () => {
        initKeaTests()

        const setQuery = jest.fn()
        const key = 'display-tab-axis-label-test'
        let query: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select company_size, accounts, revenue from numbers(2)',
            },
            display: ChartDisplayType.ActionsBar,
            chartSettings: {
                leftYAxisSettings: {
                    scale: 'logarithmic',
                },
                rightYAxisSettings: {
                    showTicks: false,
                },
            },
        }

        const props: DataVisualizationLogicProps = {
            key,
            query,
            dataNodeCollectionId: key,
            setQuery: (setter) => {
                query = setter(query)
                setQuery(query)
            },
        }

        dataVisualizationLogic(props).mount()
        displayLogic({ key }).mount()

        render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <BindLogic logic={displayLogic} props={{ key }}>
                    <DisplayTab />
                </BindLogic>
            </BindLogic>
        )

        const user = userEvent.setup()

        await user.type(await screen.findByPlaceholderText('X-axis label'), 'Company size')

        await user.click(screen.getByText('Left Y-axis'))
        await user.type(await screen.findByPlaceholderText('Left Y-axis label'), 'Accounts')

        await user.click(screen.getByText('Right Y-axis'))
        await user.type(await screen.findByPlaceholderText('Right Y-axis label'), 'Revenue')

        await waitFor(() => {
            expect(setQuery).toHaveBeenCalled()
            expect(query.chartSettings).toEqual(
                expect.objectContaining({
                    xAxisLabel: 'Company size',
                    leftYAxisSettings: expect.objectContaining({
                        label: 'Accounts',
                        scale: 'logarithmic',
                    }),
                    rightYAxisSettings: expect.objectContaining({
                        label: 'Revenue',
                        showTicks: false,
                    }),
                })
            )
        })
    })
})
