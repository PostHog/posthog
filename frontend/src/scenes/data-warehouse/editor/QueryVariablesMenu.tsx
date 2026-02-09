import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBrackets, IconChevronRight, IconExternal, IconGear } from '@posthog/icons'
import { LemonButton, LemonInput, LemonMenu, LemonMenuItems, LemonTag } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

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
    openExistingVariableModal: (variable: Variable) => void,
    closeMenu: () => void
): LemonMenuItems => {
    return variables.map((variable) => {
        const variableAsHogQL = `{variables.${variable.code_name}}`

        return {
            key: variable.id,
            custom: true,
            label: (
                <span className="flex items-center justify-between w-full gap-2 group">
                    <span className="flex flex-col gap-0.5">
                        <span>{variable.name}</span>
                        <span className="text-xxs text-muted-alt">{variable.code_name}</span>
                    </span>
                    <LemonTag type="default">{variable.type}</LemonTag>
                </span>
            ),
            sideIcon: <IconChevronRight className="text-muted-alt" />,
            items: [
                handleChange
                    ? {
                          custom: true,
                          label: () => (
                              <div className="p-2 w-full border-b mb-1">
                                  <VariableInput
                                      variable={variable}
                                      showEditingUI={false}
                                      onChange={(_, value, isNull) => {
                                          handleChange(variable, value, isNull)
                                      }}
                                      closePopover={closeMenu}
                                  />
                              </div>
                          ),
                      }
                    : null,
                {
                    label: 'Insert into query',
                    onClick: () => {
                        insertTextAtCursor(variableAsHogQL)
                        closeMenu()
                    },
                },
                {
                    label: 'Copy variable code',
                    onClick: () => {
                        void copyToClipboard(variableAsHogQL, 'variable SQL')
                        closeMenu()
                    },
                },
                {
                    label: 'Modify variable',
                    onClick: () => {
                        openExistingVariableModal(variable)
                        closeMenu()
                    },
                },
            ],
        }
    })
}

const buildOtherVariableMenuItems = (
    variables: Variable[],
    insertTextAtCursor: (text: string) => void,
    openExistingVariableModal: (variable: Variable) => void,
    closeMenu: () => void
): LemonMenuItems => {
    return variables.map((variable) => {
        const variableAsHogQL = `{variables.${variable.code_name}}`

        return {
            key: variable.id,
            custom: true,
            label: (
                <span className="flex items-center justify-between w-full gap-2 group">
                    <span className="flex flex-col gap-0.5">
                        <span>{variable.name}</span>
                        <span className="text-xxs text-muted-alt">{variable.code_name}</span>
                    </span>
                    <span className="flex items-center gap-2">
                        <LemonTag>{variable.type}</LemonTag>
                        <button
                            className="opacity-0 group-hover:opacity-100 flex items-center text-muted-alt"
                            onClick={(event) => {
                                event.stopPropagation()
                                openExistingVariableModal(variable)
                                closeMenu()
                            }}
                        >
                            <IconGear />
                        </button>
                    </span>
                </span>
            ),
            onClick: () => {
                insertTextAtCursor(variableAsHogQL)
                closeMenu()
            },
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
    const [isMenuOpen, setIsMenuOpen] = useState(false)

    const closeMenu = (): void => {
        setIsMenuOpen(false)
    }

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
        openExistingVariableModal,
        closeMenu
    )
    const variablesNotInQueryItems = buildVariableMenuItems(
        variablesNotInQuery,
        null,
        insertTextAtCursor,
        openExistingVariableModal,
        closeMenu
    )
    const otherVariablesItems = buildOtherVariableMenuItems(
        variablesNotInQuery,
        insertTextAtCursor,
        openExistingVariableModal,
        closeMenu
    )

    const searchItem = {
        custom: true,
        label: () => (
            <div className="pb-1">
                <LemonInput
                    data-attr="insight-variable-search"
                    type="search"
                    fullWidth
                    placeholder="Search variables"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    onClick={(e) => e.stopPropagation()}
                    autoFocus
                />
            </div>
        ),
    }

    const variableSections: LemonMenuItems = []

    if (!variablesLoading) {
        variableSections.push({
            title: '',
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
                items: otherVariablesItems,
            })
        }

        if (variablesUsedItems.length && variablesNotInQueryItems.length) {
            variableSections.push({
                title: 'Other variables',
                items: otherVariablesItems,
            })
        }
    }

    const manageVariablesMenuItem = {
        label: 'Manage SQL variables',
        to: urls.variables(),
        targetBlank: true,
        sideIcon: <IconExternal />,
    }

    const newVariableMenuItem = {
        label: 'New variable',
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
    }

    const menuItems: LemonMenuItems = variablesLoading
        ? [
              {
                  label: 'Loading...',
                  onClick: () => {},
              },
          ]
        : variablesUsedItems.length || variablesNotInQueryItems.length
          ? [...variableSections, manageVariablesMenuItem, newVariableMenuItem]
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
                manageVariablesMenuItem,
                newVariableMenuItem,
            ]

    return (
        <>
            <LemonMenu items={menuItems} visible={isMenuOpen} onVisibilityChange={setIsMenuOpen}>
                <LemonButton type="tertiary" size="xsmall" icon={<IconBrackets />} disabledReason={disabledReason}>
                    Variables
                </LemonButton>
            </LemonMenu>
            <NewVariableModal />
        </>
    )
}
