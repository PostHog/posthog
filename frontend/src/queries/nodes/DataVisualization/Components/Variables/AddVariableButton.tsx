import { useActions, useValues } from 'kea'

import { IconGear, IconPlus } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { NewVariableModal } from './NewVariableModal'
import { variableModalLogic } from './variableModalLogic'
import { variablesLogic } from './variablesLogic'

export const AddVariableButton = ({
    title = 'Query variable',
    buttonProps,
}: {
    title?: string
    buttonProps?: Pick<LemonButtonProps, 'type' | 'size' | 'sideIcon'>
}): JSX.Element => {
    const { showEditingUI } = useValues(dataVisualizationLogic)
    const { openNewVariableModal, openExistingVariableModal } = useActions(variableModalLogic)

    const { variablesLoading, filteredVariables, searchTerm } = useValues(variablesLogic)
    const { setSearchTerm, clickVariable } = useActions(variablesLogic)

    if (!showEditingUI) {
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
                                onClick: () => openNewVariableModal('String'),
                            },
                            {
                                label: 'Number',
                                onClick: () => openNewVariableModal('Number'),
                            },
                            {
                                label: 'Boolean',
                                onClick: () => openNewVariableModal('Boolean'),
                            },
                            {
                                label: 'List',
                                onClick: () => openNewVariableModal('List'),
                            },
                            {
                                label: 'Date',
                                onClick: () => openNewVariableModal('Date'),
                            },
                        ],
                    },
                    {
                        label: 'Existing variable',
                        custom: true,
                        items: variablesLoading
                            ? [
                                  {
                                      label: 'Loading...',
                                      onClick: () => {},
                                  },
                              ]
                            : [
                                  {
                                      label: () => (
                                          <div className="pb-1">
                                              <LemonInput
                                                  data-attr="insight-variable-search"
                                                  type="search"
                                                  placeholder="Search variables"
                                                  value={searchTerm}
                                                  onChange={setSearchTerm}
                                                  autoFocus
                                              />
                                          </div>
                                      ),
                                  },
                                  ...(filteredVariables.length
                                      ? filteredVariables.map((n) => ({
                                            label: (
                                                <span className="flex items-center justify-between w-full gap-2 group">
                                                    <span className="flex items-center gap-2">
                                                        <span>{n.name}</span>
                                                        <span className="text-xs text-muted-alt">{n.type}</span>
                                                    </span>
                                                </span>
                                            ),
                                            onClick: () => clickVariable(n),
                                            active: n.selected,
                                            sideAction: {
                                                icon: <IconGear />,
                                                onClick: (e: React.MouseEvent<HTMLButtonElement, MouseEvent>) => {
                                                    e.stopPropagation()
                                                    openExistingVariableModal(n)
                                                },
                                            },
                                        }))
                                      : [
                                            {
                                                label: 'No variables found',
                                                disabledReason: 'No variables match your search',
                                                onClick: () => {},
                                            },
                                        ]),
                              ],
                    },
                ]}
            >
                <LemonButton type="secondary" icon={<IconPlus />} sideIcon={null} {...buttonProps}>
                    {title}
                </LemonButton>
            </LemonMenu>
            <NewVariableModal />
        </>
    )
}
