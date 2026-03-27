import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DataVisualizationLogicProps, dataVisualizationLogic } from '../dataVisualizationLogic'
import { displayLogic } from '../displayLogic'
import { DisplayTab } from './DisplayTab'

const testKey = 'test-display-tab'
const dataNodeCollectionId = 'new-test-display-tab'

const query: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'select 1',
    },
    display: ChartDisplayType.ActionsBar,
    chartSettings: {},
}

describe('DisplayTab', () => {
    let dataVizLogic: ReturnType<typeof dataVisualizationLogic.build>

    beforeEach(() => {
        initKeaTests()

        const props: DataVisualizationLogicProps = {
            key: testKey,
            query,
            dataNodeCollectionId,
        }

        dataVizLogic = dataVisualizationLogic(props)
        dataVizLogic.mount()

        render(
            <Provider>
                <BindLogic logic={dataVisualizationLogic} props={props}>
                    <BindLogic logic={displayLogic} props={{ key: testKey }}>
                        <DisplayTab />
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
    })

    afterEach(() => {
        cleanup()
        dataVizLogic.unmount()
    })

    it('shows the values on series toggle unchecked by default and updates chart settings when toggled', async () => {
        const toggle = screen.getByRole('switch', { name: 'Show values on series' })
        const switchWrapper = toggle.closest('.LemonSwitch')

        expect(switchWrapper).not.toHaveClass('LemonSwitch--checked')
        expect(dataVizLogic.values.chartSettings.showValuesOnSeries).toBeUndefined()

        await userEvent.click(toggle)

        expect(switchWrapper).toHaveClass('LemonSwitch--checked')
        expect(dataVizLogic.values.chartSettings.showValuesOnSeries).toBe(true)
    })
})
