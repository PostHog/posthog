import { createContext } from 'react'

/** The scope of the preview person, such as one workflow or one broadcast. Outside any scope, previews share one person. */
export const EmailPreviewScopeContext = createContext<string>('email-preview')
