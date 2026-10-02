import { expectLogic } from 'kea-test-utils'

import type { NotebookComponentBlockNode } from 'lib/components/MarkdownNotebook/types'

import { initKeaTests } from '~/test/init'

import { notebookJupyterLogic } from './notebookJupyterLogic'
import { prepareNotebookJupyterCellCopy } from './notebookJupyterMode'
import { notebookNodeStalenessLogic } from './notebookNodeStalenessLogic'

const SHORT_ID = 'jupyter01'

const cell = (returnVariable: string): NotebookComponentBlockNode => ({
    id: 'block',
    type: 'component',
    tagName: 'PythonV2',
    props: { nodeId: 'copy', returnVariable, code: 'df.head()' },
})

describe('notebookJupyterLogic', () => {
    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
    })

    it('numbers finished runs in order and starts again after a restart', async () => {
        const logic = notebookJupyterLogic({ shortId: SHORT_ID })
        logic.mount()
        logic.actions.setIsActive(true)
        const staleness = notebookNodeStalenessLogic({ shortId: SHORT_ID })

        await expectLogic(logic, () => {
            staleness.actions.nodeRunFinished('a', 'done', null)
            staleness.actions.nodeRunFinished('b', 'failed', null)
            staleness.actions.nodeRunFinished('a', 'done', null)
        }).toMatchValues({ executionCounter: 3, executionCounts: { a: 3, b: 2 } })

        await expectLogic(logic, () => {
            logic.actions.resetExecutionCounter()
            staleness.actions.nodeRunFinished('b', 'done', null)
        }).toMatchValues({ executionCounter: 1, executionCounts: { a: 3, b: 1 } })
    })

    it('counts nothing for a notebook outside Jupyter mode', async () => {
        const logic = notebookJupyterLogic({ shortId: SHORT_ID })
        logic.mount()

        await expectLogic(logic, () => {
            notebookNodeStalenessLogic({ shortId: SHORT_ID }).actions.nodeRunFinished('a', 'done', null)
        }).toMatchValues({ executionCounter: 0, executionCounts: {} })
    })

    it.each([
        ['a generated frame name gets a fresh suffix', 'df_1a2b3c4d', /^df_(?!1a2b3c4d)[0-9a-f]{8}$/],
        ['a SQL frame name keeps its prefix', 'sql_df_1a2b3c4d', /^sql_df_(?!1a2b3c4d)[0-9a-f]{8}$/],
        ['a name the user typed is kept', 'weekly', /^weekly$/],
    ])('a pasted cell: %s', (_, returnVariable, expected) => {
        expect(prepareNotebookJupyterCellCopy(cell(returnVariable)).props.returnVariable).toMatch(expected)
    })
})
