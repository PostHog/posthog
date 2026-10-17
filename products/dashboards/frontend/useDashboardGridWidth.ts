import { useEffect, useState } from 'react'

export function useDashboardGridWidth(width: number): number {
    const [gridWidth, setGridWidth] = useState(width)
    useEffect(() => {
        if (width <= 0) {
            return
        }
        const timer = setTimeout(() => setGridWidth(width), 100)
        return () => clearTimeout(timer)
    }, [width])
    return gridWidth
}
