import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { userLogic } from 'scenes/userLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { useStorybookMocks } from '~/mocks/browser'
import { DEFAULT_PICKER_COLORS } from '~/queries/nodes/DataVisualization/Components/ConditionalFormatting/ConditionalFormattingTab'
import { DataTableVisualization } from '~/queries/nodes/DataVisualization/DataVisualization'
import {
    ConditionalFormattingRule,
    DataVisualizationNode,
    HogQLQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

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

// One rule per default palette color, for both the "light rule" and "dark rule" columns, so every
// color is exercised both as a rule saved in light mode and as one saved in dark mode.
const conditionalFormatting: ConditionalFormattingRule[] = DEFAULT_PICKER_COLORS.flatMap((hex) => [
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
            { column: 'light', settings: { display: { label: 'Rule saved in light mode' } } },
            { column: 'dark', settings: { display: { label: 'Rule saved in dark mode' } } },
        ],
        conditionalFormatting,
    },
}

// Each row shows a color's hex in both rule columns, so the cell text sits on its own color and its
// legibility is obvious.
const cachedResults: HogQLQueryResponse<string[][]> = {
    results: DEFAULT_PICKER_COLORS.map((hex) => [hex, hex, hex]),
    columns: ['color', 'light', 'dark'],
    types: [
        ['color', 'String'],
        ['light', 'String'],
        ['dark', 'String'],
    ],
}

// The table computes cell colors in JS from `themeLogic.isDarkModeOn`, which the snapshot runner's
// body-attribute theme flip does NOT reach (it only switches CSS variables). So each story pins one
// theme end to end: the user is mocked with the matching `theme_mode` (kea side) and the story
// globals pin the body attribute (CSS side). Rendering is held until `isDarkModeOn` reflects the
// mocked user, so the snapshot's waitForSelector can't fire while the other theme's colors are up.
function ConditionalFormattingTable({ mode }: { mode: 'light' | 'dark' }): JSX.Element | null {
    useStorybookMocks({
        get: {
            '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, theme_mode: mode }],
        },
    })
    const { user } = useValues(userLogic)
    const { loadUser } = useActions(userLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    // The KeaStory decorator mounts userLogic (kicking off the initial user load) before this
    // render registers the mock override above, so if the default user won that race, fetch once
    // more with the override in place.
    useEffect(() => {
        if (user && user.theme_mode !== mode) {
            loadUser()
        }
    }, [user, mode, loadUser])

    if (user?.theme_mode !== mode || isDarkModeOn !== (mode === 'dark')) {
        return null
    }

    return (
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
    )
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

// Light theme: light-saved rules render their raw color, dark-saved rules are lightened by 30.
export const ConditionalFormattingLight: Story = {
    globals: { theme: 'light' },
    parameters: { testOptions: { skipDarkMode: true } },
    render: () => <ConditionalFormattingTable mode="light" />,
}

// Dark theme: dark-saved rules render their raw color, light-saved rules are darkened by 30.
export const ConditionalFormattingDark: Story = {
    globals: { theme: 'dark' },
    parameters: { testOptions: { skipLightMode: true } },
    render: () => <ConditionalFormattingTable mode="dark" />,
}
