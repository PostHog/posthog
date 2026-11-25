import { createContext } from 'react'

/** A widget that loads data loads it again when this changes. A widget rendered on its own can leave it at zero. */
export const RefreshContext = createContext(0)
