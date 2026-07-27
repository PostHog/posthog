interface SortState {
    column: string
    direction: 'ASC' | 'DESC'
}

interface UseSortableColumnsReturn {
    handleColumnClick: (column: string) => void
    renderSortableColumnTitle: (column: string, title: string) => JSX.Element
}

export function useSortableColumns(
    currentSort: SortState,
    setSort: (column: string, direction: 'ASC' | 'DESC') => void
): UseSortableColumnsReturn {
    const handleColumnClick = (column: string): void => {
        // Toggle sort direction if clicking same column, otherwise default to DESC
        const newDirection = currentSort.column === column && currentSort.direction === 'DESC' ? 'ASC' : 'DESC'
        setSort(column, newDirection)
    }

    const renderSortableColumnTitle = (column: string, title: string): JSX.Element => {
        const isSorted = currentSort.column === column
        const direction = currentSort.direction
        return (
            <span
                onClick={() => handleColumnClick(column)}
                style={{ cursor: 'pointer', userSelect: 'none' }}
                className="flex items-center gap-1"
            >
                {title}
                {isSorted && (direction === 'DESC' ? ' ▼' : ' ▲')}
            </span>
        )
    }

    return { handleColumnClick, renderSortableColumnTitle }
}
