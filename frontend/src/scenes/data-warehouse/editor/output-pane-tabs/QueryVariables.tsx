import clsx from 'clsx'
import { useActions } from 'kea'
import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AddVariableButton } from '~/queries/nodes/DataVisualization/Components/Variables/AddVariableButton'
import { NewVariableModal } from '~/queries/nodes/DataVisualization/Components/Variables/NewVariableModal'
import { VariableComponent } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'

const documentationUrl = 'https://posthog.com/docs/sql/variables'

export function QueryVariables(): JSX.Element {
    const { variablesForInsight } = useValues(variablesLogic)
    const { updateVariableValue, removeVariable } = useActions(variablesLogic)
    const { showEditingUI } = useValues(dataVisualizationLogic)
    const { variableOverridesAreSet } = useValues(dataNodeLogic)
    const { openExistingVariableModal } = useActions(variableModalLogic)

    return (
        <div className="flex flex-col gap-1.5" data-attr="sql-editor-sidebar-query-variables-pane">
            <div className="flex flex-col items-start">
                <h3 className="mb-0">Query variables</h3>
                <span className="text-xs">
                    Query variables let you dynamically set values in your SQL query.{' '}
                    <Link to={documentationUrl} target="_blank">
                        Learn more
                    </Link>
                </span>
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
