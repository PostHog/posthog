declare module 'react-virtualized-auto-sizer' {
    import type { CSSProperties, ReactNode } from 'react'

    export interface Size {
        height: number
        width: number
    }

    export interface AutoSizerChildProps {
        height: number | undefined
        width: number | undefined
    }

    export interface AutoSizerProps {
        box?: 'border-box' | 'content-box' | 'device-pixel-content-box'
        className?: string
        'data-testid'?: string
        id?: string | number
        nonce?: string
        onResize?: (size: Size) => void
        style?: CSSProperties
        tagName?: string
        renderProp?: (params: AutoSizerChildProps) => ReactNode
        ChildComponent?: React.ComponentType<AutoSizerChildProps>
        Child?: React.ComponentType<AutoSizerChildProps>
    }

    export function AutoSizer(props: AutoSizerProps): JSX.Element
    export { AutoSizerChildProps as SizeProps }
}
