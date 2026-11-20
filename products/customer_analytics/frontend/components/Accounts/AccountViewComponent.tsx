import { getAccountViewComponentByKind, type AccountViewComponentKind } from './accountViewComponents'
import type { AccountViewWidgetProps } from './accountViewTileConfig'

interface AccountViewComponentProps extends AccountViewWidgetProps {
    kind: AccountViewComponentKind
}

export function AccountViewComponent({
    kind,
    embedded = true,
    ...widgetProps
}: AccountViewComponentProps): JSX.Element | null {
    const Component = getAccountViewComponentByKind(kind)?.Component
    return Component ? <Component embedded={embedded} {...widgetProps} /> : null
}
