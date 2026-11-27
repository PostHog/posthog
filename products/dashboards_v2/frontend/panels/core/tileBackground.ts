import { createContext, useContext, useEffect } from 'react'

/** The tile a panel sits in listens here. A panel rendered on its own has no tile, so nothing listens. */
export const TileBackgroundContext = createContext<(color: string | null) => void>(() => {})

/**
 * Sets the tile's background from the panel's own code, such as red while a number is past its limit. Pass one of
 * `ACCENT_COLORS` or any CSS color. It wins over the color a person picked, and null gives that color back.
 */
export function useTileBackground(color: string | null): void {
    const setBackground = useContext(TileBackgroundContext)
    useEffect(() => {
        setBackground(color)
        return () => setBackground(null)
    }, [setBackground, color])
}
