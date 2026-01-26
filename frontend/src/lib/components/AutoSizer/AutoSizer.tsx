import { useRef } from 'react'
import {
    AutoSizer as BaseAutoSizer,
    type AutoSizerProps as BaseAutoSizerProps,
    type SizeProps,
} from 'react-virtualized-auto-sizer'

type AutoSizerProps = Omit<BaseAutoSizerProps, 'box'> & {
    disableWidth?: boolean
    disableHeight?: boolean
}

/**
 * Wrapper around react-virtualized-auto-sizer that:
 *
 * 1. Uses offsetHeight/offsetWidth for measurement instead of getBoundingClientRect().
 *    This is necessary because getBoundingClientRect() is affected by CSS transforms
 *    (like the scale transform used in LemonModal's opening animation), which causes
 *    incorrect initial measurements.
 *
 * 2. Supports disableWidth/disableHeight props (not available in the base package)
 *    to prevent unnecessary re-renders when only one dimension matters.
 */
export function AutoSizer({ disableWidth, disableHeight, ...props }: AutoSizerProps): JSX.Element {
    const frozenWidth = useRef<number | undefined>(undefined)
    const frozenHeight = useRef<number | undefined>(undefined)

    const wrapRenderProp = (
        renderProp: (size: SizeProps) => React.ReactNode
    ): ((size: SizeProps) => React.ReactNode) => {
        return ({ width, height }: SizeProps) => {
            if (disableWidth && width !== undefined && frozenWidth.current === undefined) {
                frozenWidth.current = width
            }
            if (disableHeight && height !== undefined && frozenHeight.current === undefined) {
                frozenHeight.current = height
            }

            return renderProp({
                width: disableWidth ? frozenWidth.current : width,
                height: disableHeight ? frozenHeight.current : height,
            })
        }
    }

    const modifiedProps = { ...props }
    if ('renderProp' in modifiedProps && modifiedProps.renderProp) {
        modifiedProps.renderProp = wrapRenderProp(modifiedProps.renderProp)
    }

    return <BaseAutoSizer box="device-pixel-content-box" {...modifiedProps} />
}
