import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AddVariableButton } from '~/queries/nodes/DataVisualization/Components/Variables/AddVariableButton'
import { NewVariableModal } from '~/queries/nodes/DataVisualization/Components/Variables/NewVariableModal'
import { VariableComponent } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'

import { multitabEditorLogic } from '../multitabEditorLogic'

const documentationUrl = 'https://posthog.com/docs/sql/variables'

export function QueryVariables(): JSX.Element {
    const { variablesForInsight } = useValues(variablesLogic)
    const { updateVariableValue, removeVariable } = useActions(variablesLogic)
    const { showEditingUI } = useValues(dataVisualizationLogic)
    const { variableOverridesAreSet } = useValues(dataNodeLogic)
    const { openExistingVariableModal } = useActions(variableModalLogic)
    const { insertTextAtCursor } = useActions(multitabEditorLogic)

    return (
        <div className="overflow-auto" data-attr="sql-editor-sidebar-query-variables-pane">
            <div className="flex flex-row items-center gap-2">
                <h3 className="mb-0">Query variables</h3>
            </div>
            <div className="space-y-2">
                <p className="text-xs">
                    Query variables let you dynamically set values in your SQL query. Add a variable and then use it in
                    your HogQL query. The value you set here can be changed when viewing the insight or dashboard.
                    <br />
                    <Link to={documentationUrl} target="_blank">
                        Learn more about variables
                    </Link>
                </p>
            </div>
            <div
                className={clsx(
                    'flex gap-4 flex-col items-start',
                    variablesForInsight.length === 0 && 'h-full items-center justify-center'
                )}
            >
                {variablesForInsight.map((n) => (
                    <VariableComponent
                        key={n.id}
                        variable={n}
                        showEditingUI={showEditingUI}
                        onChange={updateVariableValue}
                        onInsertAtCursor={insertTextAtCursor}
                        onRemove={removeVariable}
                        variableOverridesAreSet={variableOverridesAreSet}
                        variableSettingsOnClick={() => openExistingVariableModal(n)}
                    />
                ))}
            </div>
            <div className="self-start">
                <AddVariableButton buttonProps={{ type: 'primary', size: 'small' }} title="Add variable" />
            </div>
            <NewVariableModal />
        </div>
    )
}
