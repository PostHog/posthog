import { createContext } from 'react'
import type { ReactNode } from 'react'

/**
 * The "isn't receiving data yet" reminder a skipped-but-still-empty product scene shows.
 * The empty-state gate publishes it here so the SceneMenuBar can render it just below the
 * bar instead of above the whole scene. Defaults to null — scenes without one render nothing.
 */
export const SetupReminderContext = createContext<ReactNode>(null)
