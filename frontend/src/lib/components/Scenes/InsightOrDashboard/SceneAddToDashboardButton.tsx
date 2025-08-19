import { IconPlusSmall } from '@posthog/icons'

import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'

import { SceneDataAttrKeyProps } from '../utils'

type SceneAddToDashboardButtonProps = SceneDataAttrKeyProps &
    Pick<ButtonPrimitiveProps, 'disabledReasons'> & {
        dashboard?: {
            onClick?: () => void
        }
    }

export function SceneAddToDashboardButton({
    dataAttrKey,
    dashboard,
    disabledReasons,
}: SceneAddToDashboardButtonProps): JSX.Element | null {
    if (!dashboard) {
        return null
    }

    return (
        <ButtonPrimitive
            menuItem
            onClick={() => {
                dashboard.onClick?.()
            }}
            data-attr={`${dataAttrKey}-add-to-dashboard-button`}
            disabledReasons={disabledReasons}
        >
            <IconPlusSmall /> Add to dashboard
        </ButtonPrimitive>
    )
}
