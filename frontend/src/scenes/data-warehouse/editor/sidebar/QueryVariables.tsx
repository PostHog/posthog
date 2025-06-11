import { LemonDivider, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions } from 'kea'
import { useValues } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AddVariableButton } from '~/queries/nodes/DataVisualization/Components/Variables/AddVariableButton'
import { NewVariableModal } from '~/queries/nodes/DataVisualization/Components/Variables/NewVariableModal'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import { VariableComponent } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
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
        <div
            className="flex flex-col gap-2 py-2 h-full overflow-auto"
            data-attr="sql-editor-sidebar-query-variables-pane"
        >
            <div className="flex flex-row items-center justify-between px-2">
                <h3 className="text-sm font-semibold mb-0">Query variables</h3>
                <AddVariableButton buttonProps={{ type: 'primary', size: 'xsmall' }} title="" />
            </div>
            <div className="flex flex-row items-center justify-between px-2">
                <span className="text-xs text-muted-alt">
                    Query variables let you dynamically set values in your SQL query.{' '}
                    <Link to={documentationUrl} target="_blank">
                        Learn more
                    </Link>
                </span>
            </div>
            <LemonDivider />
            <div
                className={clsx(
                    'flex gap-4 flex-col px-2',
                    variablesForInsight.length === 0 && 'h-full items-center justify-center'
                )}
            >
                {variablesForInsight.length === 0 && (
                    <span className="text-xs text-muted-alt">No query variables found</span>
                )}
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
            <NewVariableModal />
        </div>
    )
}
