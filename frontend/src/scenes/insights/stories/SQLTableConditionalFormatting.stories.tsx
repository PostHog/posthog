import { Meta, StoryObj } from '@storybook/react'

import { DataTableVisualization } from '~/queries/nodes/DataVisualization/DataVisualization'
import {
    ConditionalFormattingRule,
    DataVisualizationNode,
    HogQLQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

const PALETTE: { hex: string; name: string }[] = [
    { hex: '#FFADAD', name: 'Red (default)' },
    { hex: '#E8A598', name: 'Salmon' },
    { hex: '#FFD6A5', name: 'Orange' },
    { hex: '#FFCFD2', name: 'Pink' },
    { hex: '#FDFFB6', name: 'Yellow' },
    { hex: '#C1FBA4', name: 'Green' },
    { hex: '#9BF6FF', name: 'Cyan' },
    { hex: '#A0C4FF', name: 'Blue' },
    { hex: '#BDB2FF', name: 'Purple' },
    { hex: '#FFC6FF', name: 'Magenta' },
]

// Compiled Hog for the "equals" template (`return value == input`): reads the `value` and `input`
// globals, compares them (EQ = 11) and returns (RETURN = 38).
const EQUALS_BYTECODE: (string | number)[] = ['_H', 1, 32, 'input', 1, 1, 32, 'value', 1, 1, 11, 38]

function equalsRule(columnName: string, hex: string, colorMode: 'light' | 'dark'): ConditionalFormattingRule {
    return {
        id: `${colorMode}-${hex}`,
        templateId: 'equals',
        columnName,
        input: hex,
        color: hex,
        colorMode,
        bytecode: EQUALS_BYTECODE,
    }
}

// One rule per default palette color, for both the "light" and "dark" columns, so every color is
// exercised as a light-mode-saved rule and a dark-mode-saved rule.
const conditionalFormatting: ConditionalFormattingRule[] = PALETTE.flatMap(({ hex }) => [
    equalsRule('light', hex, 'light'),
    equalsRule('dark', hex, 'dark'),
])

const query: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT color, hex AS light, hex AS dark FROM palette',
    },
    display: ChartDisplayType.ActionsTable,
    tableSettings: {
        columns: [
            { column: 'color' },
            { column: 'light', settings: { display: { label: 'Light mode' } } },
            { column: 'dark', settings: { display: { label: 'Dark mode' } } },
        ],
        conditionalFormatting,
    },
}

// Each row shows a color's hex in both the light and dark columns, so the cell text sits on its own
// color and its legibility is obvious.
const cachedResults: HogQLQueryResponse<string[][]> = {
    results: PALETTE.map(({ hex, name }) => [name, hex, hex]),
    columns: ['color', 'light', 'dark'],
    types: [
        ['color', 'String'],
        ['light', 'String'],
        ['dark', 'String'],
    ],
}

type Story = StoryObj<typeof DataTableVisualization>
const meta: Meta<typeof DataTableVisualization> = {
    title: 'Scenes-App/Insights/SQLTableConditionalFormatting',
    component: DataTableVisualization,
    parameters: {
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '.DataVisualizationTable',
        },
    },
}

export default meta

// Renders just the table (not the whole insight scene). Storybook snapshots both light and dark
// themes automatically, so together they show each default color rendered in both modes with
// readable text.
export const ConditionalFormatting: Story = {
    render: () => (
        <div className="p-4">
            <DataTableVisualization
                uniqueKey="conditional-formatting"
                query={query}
                setQuery={() => {}}
                cachedResults={cachedResults}
                readOnly
                embedded
            />
        </div>
    ),
}
