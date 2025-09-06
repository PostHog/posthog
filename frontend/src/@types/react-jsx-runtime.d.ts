/**
 * Minimal jsx-runtime type declarations for React 18 compatibility with @types/react@^17
 *
 * This file provides the missing jsx-runtime types that are required when using:
 * - React 18.x with the new JSX transform
 * - @types/react@^17.x (which doesn't include jsx-runtime types)
 * - TypeScript "jsx": "react-jsx" configuration
 *
 * This can be removed when @types/react is upgraded to v18+
 */
declare module 'react/jsx-runtime' {
    import { ReactElement, JSXElementConstructor } from 'react'

    export function jsx(type: string | JSXElementConstructor<any>, props?: any, key?: React.Key): ReactElement

    export function jsxs(type: string | JSXElementConstructor<any>, props?: any, key?: React.Key): ReactElement

    export const Fragment: React.ExoticComponent<{ children?: React.ReactNode }>
}

declare module 'react/jsx-dev-runtime' {
    export * from 'react/jsx-runtime'
}
