import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { addVariableLogic } from './addVariableLogic'
import { NewVariableModal } from './NewVariableModal'
import { variablesLogic } from './variablesLogic'

export const Variables = (): JSX.Element => {
    const { dataVisualizationProps, showEditingUI } = useValues(dataVisualizationLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const { openModal } = useActions(addVariableLogic)

    const builtVariablesLogic = variablesLogic({ key: dataVisualizationProps.key })
    const { variables, variablesLoading, variablesForInsight } = useValues(builtVariablesLogic)
    const { addVariable } = useActions(builtVariablesLogic)

    if (!featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES]) {
        return <></>
    }

    return (
        <>
            <div className="flex gap-4 justify-between flex-wrap px-px">
                {showEditingUI && (
                    <LemonMenu
                        items={[
                            {
                                title: 'New variable',
                                items: [
                                    {
                                        label: 'String',
                                        onClick: () => openModal('String'),
                                    },
                                    {
                                        label: 'Number',
                                        onClick: () => openModal('Number'),
                                    },
                                    {
                                        label: 'Boolean',
                                        onClick: () => openModal('Boolean'),
                                    },
                                    {
                                        label: 'List',
                                        onClick: () => openModal('List'),
                                    },
                                ],
                            },
                            {
                                label: 'Existing variable',
                                items: variablesLoading
                                    ? [
                                          {
                                              label: 'Loading...',
                                              onClick: () => {},
                                          },
                                      ]
                                    : variables.map((n) => ({
                                          label: n.name,
                                          onClick: () => addVariable(n.id),
                                      })),
                            },
                        ]}
                    >
                        <LemonButton type="secondary" sideIcon={<IconPlus />}>
                            Add variable
                        </LemonButton>
                    </LemonMenu>
                )}
                {variablesForInsight.map((n) => (
                    <div key={n.id}>{n.name}</div>
                ))}
            </div>
            <NewVariableModal />
        </>
    )
}
