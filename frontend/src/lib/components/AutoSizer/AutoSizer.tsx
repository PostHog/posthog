import { AutoSizer as BaseAutoSizer, type AutoSizerProps as BaseAutoSizerProps } from 'react-virtualized-auto-sizer'

type AutoSizerProps = Omit<BaseAutoSizerProps, 'box'>

/**
 * Wrapper around react-virtualized-auto-sizer that uses offsetHeight/offsetWidth
 * for measurement instead of getBoundingClientRect().
 *
 * This is necessary because getBoundingClientRect() is affected by CSS transforms
 * (like the scale transform used in LemonModal's opening animation), which causes
 * incorrect initial measurements. Using device-pixel-content-box mode ensures
 * we get the true layout dimensions regardless of transforms.
 */
export function AutoSizer(props: AutoSizerProps): JSX.Element {
    return <BaseAutoSizer box="device-pixel-content-box" {...props} />
}
