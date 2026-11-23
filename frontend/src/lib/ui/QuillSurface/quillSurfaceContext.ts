import { createContext, useContext } from 'react'

// Shared Lemon components that also render on unmigrated screens switch to their quill sibling only inside a surface
// that has moved to quill and provides this context.
export const QuillSurfaceContext = createContext(false)

export function useQuillSurface(): boolean {
    return useContext(QuillSurfaceContext)
}
