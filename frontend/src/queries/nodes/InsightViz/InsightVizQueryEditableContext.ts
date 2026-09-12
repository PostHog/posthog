import { createContext } from 'react'

/**
 * Whether the surface around an insight lets the viewer edit the query behind it. Dashboard tiles,
 * shared links and exported images all render a query they do not own, so an edit made there
 * changes nothing the viewer can see. `InsightViz` is the only provider; the default keeps anything
 * rendered outside one from offering an edit that would not stick.
 */
export const InsightVizQueryEditableContext = createContext(false)
