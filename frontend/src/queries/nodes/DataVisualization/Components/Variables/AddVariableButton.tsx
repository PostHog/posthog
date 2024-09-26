import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { addVariableLogic } from './addVariableLogic'
import { NewVariableModal } from './NewVariableModal'
import { variablesLogic } from './variablesLogic'

export const AddVariableButton = (): JSX.Element => {
    const { showEditingUI } = useValues(dataVisualizationLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openModal } = useActions(addVariableLogic)

    const { variables, variablesLoading } = useValues(variablesLogic)
    const { addVariable } = useActions(variablesLogic)

    if (!featureFlags[FEATURE_FLAGS.INSIGHT_VARIABLES] || !showEditingUI) {
        return <></>
    }

    return (
        <>
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
                                  onClick: () => addVariable({ variableId: n.id, code_name: '' }),
                              })),
                    },
                ]}
            >
                <LemonButton type="secondary" sideIcon={<IconPlus />}>
                    Add variable
                </LemonButton>
            </LemonMenu>
            <NewVariableModal />
        </>
    )
}
