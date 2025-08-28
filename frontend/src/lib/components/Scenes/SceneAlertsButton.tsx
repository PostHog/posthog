import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconWarning } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'

import { InsightLogicProps, InsightShortId } from '~/types'

import { insightAlertsLogic } from '../Alerts/insightAlertsLogic'
import { SceneDataAttrKeyProps } from './utils'

interface SceneAlertsButtonProps extends SceneDataAttrKeyProps {
    insightId: number
    insightShortId: InsightShortId
    insightLogicProps: InsightLogicProps
}

export function SceneAlertsButton({
    dataAttrKey,
    insightId,
    insightShortId,
    insightLogicProps,
}: SceneAlertsButtonProps): JSX.Element {
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
