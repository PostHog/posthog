import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBrackets, IconChevronRight, IconExternal, IconGear } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonMenu,
    LemonMenuItem,
    LemonMenuItems,
    LemonMenuSection,
    LemonTag,
} from '@posthog/lemon-ui'

import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
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

const buildVariableMenuLabel = (
    variable: Variable,
    showSettingsButton: boolean,
    openExistingVariableModal: (variable: Variable) => void,
    closeMenu: () => void
): JSX.Element => {
    const settingsButton = showSettingsButton ? (
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
    ) : null

    return (
        <span className="flex items-center justify-between w-full gap-2 group">
            <span className="flex flex-col gap-0.5">
                <span>{variable.name}</span>
                <span className="text-xxs text-muted-alt">{variable.code_name}</span>
            </span>
            <span className="flex items-center gap-2">
                <LemonTag type="default">{variable.type}</LemonTag>
                {settingsButton}
            </span>
        </span>
    )
}

const buildVariableMenuItems = (
    variables: Variable[],
    handleChange: null | ((variable: Variable, value: any, isNull: boolean) => void),
    insertTextAtCursor: (text: string) => void,
    openExistingVariableModal: (variable: Variable) => void,
    closeMenu: () => void,
    options?: { showSettingsButton?: boolean; insertOnClick?: boolean }
): LemonMenuItem[] => {
    return variables.map((variable): LemonMenuItem => {
        const variableAsHogQL = `{variables.${variable.code_name}}`
        const showSettingsButton = options?.showSettingsButton ?? false
        const insertOnClick = options?.insertOnClick ?? false

        const menuItem: LemonMenuItem = {
            key: variable.id,
            custom: true,
            label: buildVariableMenuLabel(variable, showSettingsButton, openExistingVariableModal, closeMenu),
        }

        if (insertOnClick) {
            return {
                ...menuItem,
                onClick: () => {
                    insertTextAtCursor(variableAsHogQL)
                    closeMenu()
                },
            }
        }

        return {
            ...menuItem,
            sideIcon: <IconChevronRight className="text-muted-alt" />,
            items: [
                handleChange
                    ? {
                          custom: true,
                          label: () => (
                              <div className={`p-2 w-full border-b mb-1 ${CLICK_OUTSIDE_BLOCK_CLASS}`}>
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
            ].filter((a) => a),
        } as LemonMenuItem
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
    const otherVariablesItems = buildVariableMenuItems(
        variablesNotInQuery,
        null,
        insertTextAtCursor,
        openExistingVariableModal,
        closeMenu,
        { showSettingsButton: true, insertOnClick: true }
    )

    const searchItem: LemonMenuItem = {
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

    const variableSections: LemonMenuSection[] = []

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
        } else if (variablesNotInQuery.length) {
            variableSections.push({
                title: 'Variables',
                items: otherVariablesItems,
            })
        }

        if (variablesUsedItems.length && variablesNotInQuery.length) {
            variableSections.push({
                title: 'Other variables',
                items: otherVariablesItems,
            })
        }
    }

    const manageVariablesMenuItem: LemonMenuItem = {
        label: 'Manage SQL variables',
        to: urls.variables(),
        targetBlank: true,
        sideIcon: <IconExternal />,
    }

    const newVariableMenuItem: LemonMenuItem = {
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
        : variablesUsedItems.length || variablesNotInQuery.length
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
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconBrackets />}
                    disabledReason={disabledReason}
                    data-attr="sql-editor-variables-button"
                >
                    Variables
                </LemonButton>
            </LemonMenu>
            <NewVariableModal />
        </>
    )
}
