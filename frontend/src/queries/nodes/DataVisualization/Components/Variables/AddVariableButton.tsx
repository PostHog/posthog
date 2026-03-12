import { useActions, useValues } from 'kea'

import { IconGear, IconPlus } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonInput, LemonMenu } from '@posthog/lemon-ui'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { NewVariableModal } from './NewVariableModal'
import { variableModalLogic } from './variableModalLogic'
import { variablesLogic } from './variablesLogic'

interface VariableMenuItem {
    label: JSX.Element
    onClick: () => void
    active: boolean
    sideAction: {
        icon: JSX.Element
        onClick: (e: React.MouseEvent<HTMLButtonElement, MouseEvent>) => void
    }
}

interface EmptyMenuItem {
    label: string
    disabledReason: string
    onClick: () => void
}

type MenuItem = VariableMenuItem | EmptyMenuItem

function isVariableMenuItem(item: MenuItem): item is VariableMenuItem {
    return 'active' in item
}

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

    const variableMenuItems = filteredVariables.length
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
          ]

    const menuItems = variablesLoading
        ? [
              {
                  label: 'Loading...',
                  onClick: () => {},
              },
          ]
        : [
              {
                  custom: true,
                  items: [
                      {
                          label: () => (
                              <>
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
                                  <div className="max-h-[280px] overflow-y-auto -mx-1">
                                      {variableMenuItems.map((item, index) => {
                                          const isVariable = isVariableMenuItem(item)
                                          return (
                                              <div key={index}>
                                                  <div
                                                      className={`cursor-pointer hover:bg-bg-3000 px-3 py-1.5 flex items-center justify-between gap-2 group ${
                                                          isVariable && item.active ? 'bg-bg-3000' : ''
                                                      }`}
                                                      onClick={item.onClick}
                                                  >
                                                      {item.label}
                                                      {isVariable && (
                                                          <button
                                                              className="opacity-0 group-hover:opacity-100 flex items-center"
                                                              onClick={(e) => {
                                                                  e.stopPropagation()
                                                                  item.sideAction.onClick(e)
                                                              }}
                                                          >
                                                              {item.sideAction.icon}
                                                          </button>
                                                      )}
                                                  </div>
                                              </div>
                                          )
                                      })}
                                  </div>
                              </>
                          ),
                      },
                  ],
              },
              {
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
              },
          ]

    return (
        <>
            <LemonMenu items={menuItems}>
                <LemonButton type="secondary" icon={<IconPlus />} sideIcon={null} {...buttonProps}>
                    {title}
                </LemonButton>
            </LemonMenu>
            <NewVariableModal />
        </>
    )
}
