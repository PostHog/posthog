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

function renderTableDisplay(
    key: string,
    featureFlags: Record<string, string | boolean> = {}
): () => DataVisualizationNode {
    initKeaTests()

    const flags = featureFlagLogic()
    flags.mount()
    flags.actions.setFeatureFlags(Object.keys(featureFlags), featureFlags)

    let query: DataVisualizationNode = {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select * from summaries' },
        display: ChartDisplayType.ActionsTable,
    }
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

    return () => query
}

async function selectDisplay(label: string): Promise<void> {
    const user = userEvent.setup()
    await user.click(screen.getByTestId('chart-filter'))
    await user.click(await screen.findByText(label))
}

describe('TableDisplay', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['Box plot', ChartDisplayType.BoxPlot],
        ['Horizontal bar chart', ChartDisplayType.ActionsBarValue],
    ])('offers %s and saves the selected display', async (label, display) => {
        const query = renderTableDisplay(`table-display-${display}`)

        await selectDisplay(label)

        await waitFor(() => expect(query().display).toBe(display))
    })

    it('offers metrics behind the feature flag and saves one Y-series', async () => {
        const query = renderTableDisplay('table-display-metric', { [FEATURE_FLAGS.METRIC_INSIGHT]: true })

        await selectDisplay('Metric')

        await waitFor(() => expect(query().display).toBe(ChartDisplayType.Metric))
        expect(query().chartSettings?.yAxis).toHaveLength(1)
    })
})
