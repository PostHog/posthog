import { Column, SelectedYAxis } from '../dataVisualizationLogic'
import { getAvailableSeriesBreakdownColumns } from './seriesBreakdownUtils'

const createColumn = (name: string, isNumerical: boolean): Column => ({
    name,
    type: {
        name: isNumerical ? 'INTEGER' : 'STRING',
        isNumerical,
    },
    label: name,
    dataIndex: 0,
})

const createYAxis = (name: string): SelectedYAxis => ({
    name,
    settings: {
        formatting: {
            prefix: '',
            suffix: '',
        },
    },
})

describe('getAvailableSeriesBreakdownColumns', () => {
    it('returns no breakdown columns when only the current x-axis and y-axis remain', () => {
        const columns = [createColumn('screen_width', true), createColumn('screen_height', true)]

        expect(getAvailableSeriesBreakdownColumns(columns, 'screen_width', [createYAxis('screen_height')])).toEqual([])
    })

    it('excludes the selected x-axis and y-axis columns from breakdown options', () => {
        const columns = [
            createColumn('screen_width', true),
            createColumn('screen_height', true),
            createColumn('browser', false),
        ]

        expect(getAvailableSeriesBreakdownColumns(columns, 'screen_width', [createYAxis('screen_height')])).toEqual([
            createColumn('browser', false),
        ])
    })
})
