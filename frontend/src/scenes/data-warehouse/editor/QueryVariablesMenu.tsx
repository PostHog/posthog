import { useActions, useValues } from 'kea'

import { IconBrackets, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { NewVariableModal } from '~/queries/nodes/DataVisualization/Components/Variables/NewVariableModal'
import { VariableInput } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { variableModalLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableModalLogic'
import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { dataVisualizationLogic } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { Variable } from '~/queries/nodes/DataVisualization/types'

import { multitabEditorLogic } from './multitabEditorLogic'

interface QueryVariablesMenuProps {
    disabledReason?: string
}

const buildVariableMenuItems = (
    variables: Variable[],
    handleChange: null | ((variable: Variable, value: any, isNull: boolean) => void),
    insertTextAtCursor: (text: string) => void,
    openExistingVariableModal: (variable: Variable) => void
): LemonMenuItems => {
    return variables.map((variable) => {
        const variableAsHogQL = `{variables.${variable.code_name}}`

        return {
            key: variable.id,
            custom: true,
            label: (
                <span className="flex items-center justify-between w-full gap-2 group">
                    <span className="flex items-center gap-2">
                        <span>{variable.name}</span>
                        <span className="text-xs text-muted-alt">{variable.type}</span>
                    </span>
                </span>
            ),
            sideIcon: <IconChevronRight className="text-muted-alt" />,
            items: [
                handleChange
                    ? {
                          custom: true,
                          label: () => (
                              <div className="p-2 w-full">
                                  <VariableInput
                                      variable={variable}
                                      showEditingUI={false}
                                      onChange={(_, value, isNull) => {
                                          handleChange(variable, value, isNull)
                                      }}
                                      closePopover={() => {}}
                                  />
                              </div>
                          ),
                      }
                    : null,
                {
                    label: 'Insert into query',
                    onClick: () => insertTextAtCursor(variableAsHogQL),
                },
                {
                    label: 'Copy variable code',
                    onClick: () => void copyToClipboard(variableAsHogQL, 'variable SQL'),
                },
                {
                    label: 'Modify variable',
                    onClick: () => openExistingVariableModal(variable),
                },
            ],
        }
    })
}

export function QueryVariablesMenu({ disabledReason }: QueryVariablesMenuProps): JSX.Element | null {
    const { showEditingUI } = useValues(dataVisualizationLogic)
    const { variablesLoading, variablesUsedInQuery, variablesNotInQuery, searchTerm, internalSelectedVariables } =
        useValues(variablesLogic)
    const { setSearchTerm, updateVariableValue, addVariable } = useActions(variablesLogic)
    const { openNewVariableModal, openExistingVariableModal } = useActions(variableModalLogic)
    const { insertTextAtCursor } = useActions(multitabEditorLogic)

    if (!showEditingUI) {
        return null
    }

    const selectedVariableIds = new Set(internalSelectedVariables.map((variable) => variable.variableId))

    const handleChange = (variable: Variable, value: any, isNull: boolean): void => {
        if (!selectedVariableIds.has(variable.id)) {
            addVariable({ variableId: variable.id, code_name: variable.code_name })
        }

        updateVariableValue(variable.id, value, isNull)
    }

    const variablesUsedItems = buildVariableMenuItems(
        variablesUsedInQuery,
        handleChange,
        insertTextAtCursor,
        openExistingVariableModal
    )
    const variablesNotInQueryItems = buildVariableMenuItems(
        variablesNotInQuery,
        null,
        insertTextAtCursor,
        openExistingVariableModal
    )

    const searchItem = {
        custom: true,
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
    }

    const variableSections: LemonMenuItems = []

    if (!variablesLoading) {
        variableSections.push({
            title: 'Search',
            items: [searchItem],
        })
        if (variablesUsedItems.length) {
            variableSections.push({
                title: 'Used in query',
                items: variablesUsedItems,
            })
        } else if (variablesNotInQueryItems.length) {
            variableSections.push({
                title: 'Variables',
                items: variablesNotInQueryItems,
            })
        }

        if (variablesUsedItems.length && variablesNotInQueryItems.length) {
            variableSections.push({
                title: 'Other variables',
                items: variablesNotInQueryItems,
            })
        }
    }

    const menuItems: LemonMenuItems = variablesLoading
        ? [
              {
                  label: 'Loading...',
                  onClick: () => {},
              },
          ]
        : variablesUsedItems.length || variablesNotInQueryItems.length
          ? [
                ...variableSections,
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
            ]
          : [
                {
                    items: [
                        searchItem,
                        {
                            label: 'No variables found',
                            disabledReason: 'No variables match your search',
                            onClick: () => {},
                        },
                    ],
                },
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
            ]

    return (
        <>
            <LemonMenu items={menuItems}>
                <LemonButton type="tertiary" size="xsmall" icon={<IconBrackets />} disabledReason={disabledReason}>
                    Variables
                </LemonButton>
            </LemonMenu>
            <NewVariableModal />
        </>
    )
}
