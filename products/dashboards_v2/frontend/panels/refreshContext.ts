import { createContext } from 'react'

/** A panel that loads data loads it again when this changes. A panel rendered on its own can leave it at zero. */
export const RefreshContext = createContext(0)
