import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import GridLayout, { WidthProvider } from '@mariusandra/react-grid-layout'
import { entityFilterLogic } from './entityFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'

const ReactGridLayout = WidthProvider(GridLayout)

export function ActionFilter({ setFilters, filters, typeKey, hideMathSelector }) {
    const logic = entityFilterLogic({ setFilters, filters, typeKey })

    const { localFilters } = useValues(logic)
    const { addFilter, setLocalFilters } = useActions(logic)

    // No way around this. Somehow the ordering of the logic calling each other causes stale "localFilters"
    // to be shown on the /funnels page, even if we try to use a selector with props to hydrate it
    useEffect(() => {
        setLocalFilters(filters)
    }, [filters])

    const layouts = localFilters.map((filter, index) => ({ i: index.toString(), x: 1, y: index, w: 1, h: 1, isDraggable:true}))
    const renderLocalFilters = () => localFilters.map((filter, index) => (
        <div key={index.toString()}>
          <ActionFilterRow
              logic={logic}
              filter={filter}
              index={index}
              key={index}
              hideMathSelector={hideMathSelector}
          />
        </div>
      ));

    const updateFilterRowIndex = (_layout, _oldItem, newItem) => {

    }

    return (
        <div style={{position: 'relative'}}>
          {localFilters &&
            <ReactGridLayout
              cols={1}
              layouts={layouts}
              rowHeight={39}
              onLayoutChange={() => {}}
              draggableHandle=".mt-2"
              isResizable={false}
              onDragStop={updateFilterRowIndex}
            >
              { renderLocalFilters() }
            </ReactGridLayout>
          }
          <Button
            type="primary"
            onClick={() => addFilter()}
            style={{ marginTop: '0.5rem' }}
            data-attr="add-action-event-button"
            >
            Add action/event
          </Button>
        </div>
    )
}
