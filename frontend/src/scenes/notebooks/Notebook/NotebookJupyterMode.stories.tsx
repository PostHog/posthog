import { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { notebookTestTemplate } from './__mocks__/notebook-template-for-snapshot'
import { buildMarkdownNotebookContent, serializeMarkdownNotebookComponent } from './markdownNotebookV2'
import { notebookJupyterLogic } from './notebookJupyterLogic'

const SHORT_ID = 'jupyter-mode'

const CELLS = {
    load: 'jupyter-cell-load',
    count: 'jupyter-cell-count',
    frame: 'jupyter-cell-frame',
    error: 'jupyter-cell-error',
    sql: 'jupyter-cell-sql',
}

const markdown = [
    '# Weekly signups',
    'Signups by week, from the `$signup` event. Run the cells in order.',
    serializeMarkdownNotebookComponent('PythonV2', {
        nodeId: CELLS.load,
        returnVariable: 'df_signups',
        code: "import pandas as pd\n\nprint(f'Loaded {len(events):,} events')",
        result: { columns: [], row_count: 0, stdout: 'Loaded 12,408 events\n' },
    }),
    serializeMarkdownNotebookComponent('PythonV2', {
        nodeId: CELLS.count,
        returnVariable: 'df_count',
        code: 'len(events)',
        result: { columns: [], row_count: 0, result_text: '12408' },
    }),
    serializeMarkdownNotebookComponent('PythonV2', {
        nodeId: CELLS.frame,
        returnVariable: 'df_weekly',
        code: "weekly = events.groupby('week').agg(signups=('person_id', 'nunique'))\nweekly.tail(5)",
        result: {
            columns: ['week', 'signups', 'activated', 'activation_rate'],
            row_count: 5,
            first_page: [
                ['2026-08-24', 1843, 1102, 0.598],
                ['2026-08-31', 1920, 1187, 0.618],
                ['2026-09-07', 2011, 1244, 0.619],
                ['2026-09-14', 1978, 1253, 0.633],
                ['2026-09-21', 2156, 1391, 0.645],
            ],
        },
    }),
    '## Retention',
    serializeMarkdownNotebookComponent('PythonV2', {
        nodeId: CELLS.error,
        returnVariable: 'df_retention',
        code: "retention = weekly['retained'] / weekly['signups']",
        result: {
            columns: [],
            row_count: 0,
            stderr: 'Traceback (most recent call last):\n  File "<cell>", line 1, in <module>\nKeyError: \'retained\'\n',
        },
    }),
    serializeMarkdownNotebookComponent('SQLV2', {
        nodeId: CELLS.sql,
        returnVariable: 'sql_df_events',
        code: 'select event, count() as total\nfrom events\nwhere timestamp > now() - interval 7 day\ngroup by event\norder by total desc\nlimit 3',
        result: {
            columns: ['event', 'total'],
            row_count: 3,
            first_page: [
                ['$pageview', 48213],
                ['$autocapture', 30118],
                ['$signup', 2156],
            ],
        },
    }),
].join('\n\n')

const notebook = {
    ...notebookTestTemplate('Weekly signups', []),
    short_id: SHORT_ID,
    content: buildMarkdownNotebookContent(markdown),
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks/Jupyter mode',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-28',
        pageUrl: urls.notebook(SHORT_ID),
        testOptions: {
            viewport: { width: 1400, height: 1400 },
            waitForSelector: '.MarkdownNotebook__real-node-content',
        },
    },
    decorators: [
        mswDecorator({
            post: {
                [`/api/projects/:team_id/notebooks/${SHORT_ID}/collab/markdown_save/`]: notebook,
            },
            get: {
                [`/api/projects/:team_id/notebooks/${SHORT_ID}`]: notebook,
                [`/api/projects/:team_id/notebooks/${SHORT_ID}/kernel/status`]: {
                    backend: 'modal',
                    status: 'running',
                    frames: [],
                },
                '/api/projects/:team_id/notebooks/kernel/compute_options': {
                    allowed_cpu_cores: [2],
                    allowed_memory_gb: [4],
                    presets: [],
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const JupyterModeOff: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS] },
}

export const JupyterMode: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS, FEATURE_FLAGS.NOTEBOOK_JUPYTER_MODE] },
    play: async ({ canvasElement }) => {
        await waitFor(
            () => {
                if (canvasElement.querySelectorAll('.MarkdownNotebook__jupyter-cell').length < 5) {
                    throw new Error('Jupyter cells have not rendered yet')
                }
            },
            { timeout: 30000 }
        )
        const logic = notebookJupyterLogic.findMounted({ shortId: SHORT_ID })
        ;[CELLS.load, CELLS.count, CELLS.frame, CELLS.error, CELLS.sql].forEach((nodeId, index) =>
            logic?.actions.assignExecutionCount(nodeId, index + 1)
        )

        const canvas = within(canvasElement)
        await waitFor(() => {
            if (!canvasElement.querySelector('.DataVisualization')) {
                throw new Error('SQL chart has not rendered by default')
            }
        })
        fireEvent.click(canvas.getByRole('button', { name: 'Show table' }))
        await waitFor(() => {
            canvas.getByRole('button', { name: 'Show chart' })
            if (canvasElement.querySelector('.DataVisualization')) {
                throw new Error('SQL chart is still visible after switching to the table')
            }
        })
        fireEvent.click(canvas.getByRole('button', { name: 'Show chart' }))
        await waitFor(() => canvas.getByRole('button', { name: 'Show table' }))
    },
}
