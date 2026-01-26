import {
    AutoSizer as BaseAutoSizer,
    type AutoSizerProps as BaseAutoSizerProps,
    type SizeProps,
} from 'react-virtualized-auto-sizer'

type AutoSizerProps = BaseAutoSizerProps & {
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
 *    to prevent unnecessary re-renders when only one dimension matters. When disabled,
 *    that dimension is passed as undefined (matching react-virtualized behavior).
 */
export function AutoSizer({ disableWidth, disableHeight, ...props }: AutoSizerProps): JSX.Element {
    const wrapRenderProp = (
        renderProp: (size: SizeProps) => React.ReactNode
    ): ((size: SizeProps) => React.ReactNode) => {
        return ({ width, height }: SizeProps) => {
            return renderProp({
                width: disableWidth ? undefined : width,
                height: disableHeight ? undefined : height,
            })
        }
    }

    const modifiedProps: BaseAutoSizerProps = { ...props, box: props.box || 'device-pixel-content-box' }
    if ('renderProp' in modifiedProps && modifiedProps.renderProp) {
        modifiedProps.renderProp = wrapRenderProp(modifiedProps.renderProp)
    }

    return <BaseAutoSizer {...modifiedProps} />
}
