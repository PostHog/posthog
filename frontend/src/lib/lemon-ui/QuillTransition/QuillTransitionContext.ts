import { createContext } from 'react'

/**
 * True when the `today-rail-nav` redesign is on, so shared Lemon components render their quill version.
 * `QuillTransitionProvider` reads the flag once at the app root, so each component instance does not subscribe
 * to feature flags. Roots outside the provider (Storybook, `LemonDialog.open`) get `false` and keep LemonUI.
 */
export const QuillTransitionContext = createContext<boolean>(false)
