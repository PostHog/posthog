import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { IconWarning } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { InsightLogicProps, InsightShortId } from '~/types'
import { insightAlertsLogic } from '../Alerts/insightAlertsLogic'
import { SceneDataAttrKeyProps } from './utils'
import { urls } from 'scenes/urls'

interface SceneSubscribeButtonProps extends SceneDataAttrKeyProps {
    insightId: number
    insightShortId: InsightShortId
    insightLogicProps: InsightLogicProps
}

export function SceneAlertsButton({
    dataAttrKey,
    insightId,
    insightShortId,
    insightLogicProps,
}: SceneSubscribeButtonProps): JSX.Element {
    const { push } = useActions(router)

    const logic = insightAlertsLogic({ insightId, insightLogicProps })
    const { alerts } = useValues(logic)

    return (
        <ButtonPrimitive
            menuItem
            onClick={() => push(urls.insightAlerts(insightShortId))}
            data-attr={`${dataAttrKey}-alerts-dropdown-menu-item`}
        >
            <IconWithCount count={alerts?.length} showZero={false}>
                <IconWarning />
            </IconWithCount>
            Alerts
        </ButtonPrimitive>
    )
}
