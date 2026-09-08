import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from '../dataVisualizationLogic'
import { TableDisplay } from './TableDisplay'

const cachedResults: HogQLQueryResponse = {
    results: [['Mon', 1, 2, 3, 4, 5, 6]],
    columns: ['bucket', 'min', 'p25', 'median', 'mean', 'p75', 'max'],
    types: [
        ['bucket', 'String'],
        ['min', 'Float64'],
        ['p25', 'Float64'],
        ['median', 'Float64'],
        ['mean', 'Float64'],
        ['p75', 'Float64'],
        ['max', 'Float64'],
    ],
}

describe('TableDisplay', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['Box plot', ChartDisplayType.BoxPlot, false],
        ['Metric', ChartDisplayType.Metric, true],
    ])('offers %s and saves the selected display', async (label, display, metricInsightEnabled) => {
        initKeaTests()

        if (metricInsightEnabled) {
            const flags = featureFlagLogic()
            flags.mount()
            flags.actions.setFeatureFlags([FEATURE_FLAGS.METRIC_INSIGHT], { [FEATURE_FLAGS.METRIC_INSIGHT]: true })
        }

        let query: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: { kind: NodeKind.HogQLQuery, query: 'select * from summaries' },
            display: ChartDisplayType.ActionsTable,
        }
        const key = `table-display-${display}`
        const props: DataVisualizationLogicProps = {
            key,
            query,
            cachedResults,
            dataNodeCollectionId: key,
            setQuery: (setter) => {
                query = setter(query)
            },
        }

        dataNodeLogic({
            key: props.key,
            query: query.source,
            cachedResults,
            dataNodeCollectionId: props.dataNodeCollectionId,
        }).mount()
        dataVisualizationLogic(props).mount()

        render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <TableDisplay />
            </BindLogic>
        )

        const user = userEvent.setup()
        await user.click(screen.getByTestId('chart-filter'))
        await user.click(await screen.findByText(label))

        await waitFor(() => expect(query.display).toBe(display))
        if (display === ChartDisplayType.Metric) {
            expect(query.chartSettings?.yAxis).toHaveLength(1)
        }
    })
})
