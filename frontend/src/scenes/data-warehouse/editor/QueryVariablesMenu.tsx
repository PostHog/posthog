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
import { urls } from 'scenes/urls'

import { NewVariableModal } from '~/queries/nodes/DataVisualization/Components/Variables/NewVariableModal'
import { VariableInput } from '~/queries/nodes/DataVisualization/Components/Variables/Variables'
import { Variable } from '~/queries/nodes/DataVisualization/types'

import { NEW_VARIABLE_TYPES, QueryVariablesState, useQueryVariablesState } from './useQueryVariablesState'

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
    state: QueryVariablesState,
    closeMenu: () => void,
    options?: { showSettingsButton?: boolean; insertOnClick?: boolean; canSetValue?: boolean; canRemove?: boolean }
): LemonMenuItem[] => {
    return variables.map((variable): LemonMenuItem => {
        const showSettingsButton = options?.showSettingsButton ?? false
        const insertOnClick = options?.insertOnClick ?? false

        const menuItem: LemonMenuItem = {
            key: variable.id,
            custom: true,
            label: buildVariableMenuLabel(variable, showSettingsButton, state.edit, closeMenu),
        }

        if (insertOnClick) {
            return {
                ...menuItem,
                onClick: () => {
                    state.insert(variable)
                    closeMenu()
                },
            }
        }

        return {
            ...menuItem,
            sideIcon: <IconChevronRight className="text-muted-alt" />,
            items: [
                options?.canSetValue
                    ? {
                          custom: true,
                          label: () => (
                              <div className={`p-2 w-full border-b mb-1 ${CLICK_OUTSIDE_BLOCK_CLASS}`}>
                                  <VariableInput
                                      variable={variable}
                                      showEditingUI={false}
                                      onChange={(_, value, isNull) => {
                                          state.setValue(variable, value, isNull)
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
                        state.insert(variable)
                        closeMenu()
                    },
                },
                options?.canRemove
                    ? {
                          label: 'Remove from this query',
                          onClick: () => {
                              state.remove(variable)
                              closeMenu()
                          },
                      }
                    : null,
                {
                    label: 'Copy variable code',
                    onClick: () => {
                        state.copyCode(variable)
                        closeMenu()
                    },
                },
                {
                    label: 'Modify variable',
                    onClick: () => {
                        state.edit(variable)
                        closeMenu()
                    },
                },
            ].filter((a) => a),
        } as LemonMenuItem
    })
}

export function QueryVariablesMenu({ disabledReason }: QueryVariablesMenuProps): JSX.Element | null {
    const state = useQueryVariablesState()
    const [isMenuOpen, setIsMenuOpen] = useState(false)
    const hasVariablesInUse = state.usedInQuery.length > 0

    const closeMenu = (): void => {
        setIsMenuOpen(false)
    }

    if (!state.showEditingUI) {
        return null
    }

    const variablesUsedItems = buildVariableMenuItems(state.usedInQuery, state, closeMenu, { canSetValue: true })
    const unusedVariablesItems = buildVariableMenuItems(state.unusedWithValues, state, closeMenu, {
        canSetValue: true,
        canRemove: true,
    })
    const otherVariablesItems = buildVariableMenuItems(state.other, state, closeMenu, {
        showSettingsButton: true,
        insertOnClick: true,
    })

    const searchItem: LemonMenuItem = {
        custom: true,
        label: () => (
            <div className="pb-1">
                <LemonInput
                    data-attr="insight-variable-search"
                    type="search"
                    fullWidth
                    placeholder="Search variables"
                    value={state.searchTerm}
                    onChange={state.setSearchTerm}
                    onClick={(e) => e.stopPropagation()}
                    autoFocus
                />
            </div>
        ),
    }

    const variableSections: LemonMenuSection[] = []

    if (!state.loading) {
        variableSections.push({
            title: '',
            items: [searchItem],
        })
        if (variablesUsedItems.length) {
            variableSections.push({
                title: 'Used in query',
                items: variablesUsedItems,
            })
        }
        if (unusedVariablesItems.length) {
            variableSections.push({
                title: 'Unused in query (values retained)',
                items: unusedVariablesItems,
            })
        }
        if (otherVariablesItems.length) {
            variableSections.push({
                title: variablesUsedItems.length || unusedVariablesItems.length ? 'Other variables' : 'Variables',
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

    // The menu's visibility is controlled, so clicking a nested item only closes the
    // submenu — close the whole menu explicitly before handing over to the modal.
    const newVariableMenuItem: LemonMenuItem = {
        label: 'New variable',
        items: NEW_VARIABLE_TYPES.map((variableType) => ({
            label: variableType,
            onClick: () => {
                closeMenu()
                state.create(variableType)
            },
        })),
    }

    const menuItems: LemonMenuItems = state.loading
        ? [
              {
                  label: 'Loading...',
                  onClick: () => {},
              },
          ]
        : variablesUsedItems.length || unusedVariablesItems.length || otherVariablesItems.length
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
                    type="secondary"
                    size="small"
                    icon={
                        <span className="relative inline-flex">
                            <IconBrackets />
                            {hasVariablesInUse ? (
                                <span className="absolute -top-0.5 -right-1 block h-2 w-2 rounded-full bg-danger" />
                            ) : null}
                        </span>
                    }
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
