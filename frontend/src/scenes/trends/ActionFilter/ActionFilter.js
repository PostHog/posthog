import React, { useEffect, useState } from 'react'
import { useActions, useValues } from 'kea'
import GridLayout, { WidthProvider } from '@mariusandra/react-grid-layout'
import { entityFilterLogic } from './entityFilterLogic'
import { ActionFilterRow } from './ActionFilterRow'
import { Button } from 'antd'

const ReactGridLayout = WidthProvider(GridLayout)

export function ActionFilter({ setFilters, filters, typeKey, hideMathSelector }) {
    const logic = entityFilterLogic({ setFilters, filters, typeKey })

    const { localFilters, layouts } = useValues(logic)
    const { addFilter, orderFilters, setLocalFilters } = useActions(logic)
    // This is to be able to collapse a row when it is being dragged due to a bug
    // with reac-grid-layout that doesn't seems to work when a row is open
    const [draggedRow, setDraggedRow] = useState(null)

    // No way around this. Somehow the ordering of the logic calling each other causes stale "localFilters"
    // to be shown on the /funnels page, even if we try to use a selector with props to hydrate it
    useEffect(() => {
        setLocalFilters(filters)
    }, [filters])

    const renderLocalFilters = () =>
        localFilters.map((filter, index) => (
            <div
                key={filter.id ? filter.id.toString() : filter.id}
                data-grid={layouts.find((layout) => layout.i === filter.id)}
            >
                <ActionFilterRow
                    logic={logic}
                    filter={filter}
                    index={index}
                    key={index}
                    hideMathSelector={hideMathSelector}
                    dragging={draggedRow === filter.id}
                />
            </div>
        ))
    // eslint-disable-next-line no-unused-vars
    const updateFilterPositions = (layout, _oldItem, _newItem) => {
        setDraggedRow(null)
        const filterPositions = layout.reduce((positions, filter) => {
            positions[filter.i] = filter.y
            return positions
        }, {})
        orderFilters(filterPositions)
    }

    // eslint-disable-next-line no-unused-vars
    const collapseFilter = (_layout, _oldItem, newItem) => {
        setDraggedRow(Number(newItem.i))
    }

    return (
        <div style={{ position: 'relative' }}>
            {localFilters && (
                <ReactGridLayout
                    cols={1}
                    layout={layouts}
                    margin={[0, 10]}
                    rowHeight={39}
                    onLayoutChange={() => {}}
                    draggableHandle=".action-filter-row-handle"
                    maxRows={localFilters.length}
                    isResizable={true}
                    onDragStart={collapseFilter}
                    onDragStop={updateFilterPositions}
                    // We disable this because we would have to add a lot of CSS changes
                    // to let ReactGridLayout properly render the Dropdown and Popups
                    // inside the ActionFilterRow
                    useCSSTransforms={false}
                >
                    {renderLocalFilters()}
                </ReactGridLayout>
            )}
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
