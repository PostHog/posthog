import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconWarning } from '@posthog/icons'
import { useFeatureFlagVariantKey } from '@posthog/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconWithCount } from 'lib/lemon-ui/icons/icons'
import { ButtonPrimitive, DisabledReasonsObject } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'

import { InsightLogicProps, InsightShortId } from '~/types'

import { insightAlertsLogic } from '../Alerts/insightAlertsLogic'
import { SceneDataAttrKeyProps } from './utils'

const ALERTS_LABEL_BY_VARIANT: Record<string, string> = {
    control: 'Alerts',
    'get-notified': 'Get notified',
    'monitor-changes': 'Monitor changes',
    'set-up-alert': 'Set up alert',
}

interface SceneAlertsButtonProps extends SceneDataAttrKeyProps {
    insightId: number
    insightShortId: InsightShortId
    insightLogicProps: InsightLogicProps
    disabledReasons?: DisabledReasonsObject
}

export function SceneAlertsButton({
    disabledReasons,
    dataAttrKey,
    insightId,
    insightShortId,
    insightLogicProps,
}: SceneAlertsButtonProps): JSX.Element {
    const { push } = useActions(router)

    const logic = insightAlertsLogic({ insightId, insightLogicProps })
    const { alerts } = useValues(logic)

    const labelVariant = useFeatureFlagVariantKey(FEATURE_FLAGS.SCENE_ALERTS_LABEL_EXPERIMENT)
    const resolvedVariant = typeof labelVariant === 'string' ? labelVariant : 'control'
    const alertsLabel = ALERTS_LABEL_BY_VARIANT[resolvedVariant] ?? 'Alerts'

    return (
        <ButtonPrimitive
            menuItem
            onClick={() => {
                posthog.capture('scene alerts menu item clicked', {
                    resource_type: dataAttrKey,
                    label_variant: resolvedVariant,
                    label_text: alertsLabel,
                })
                push(urls.insightAlerts(insightShortId))
            }}
            data-attr={`${dataAttrKey}-alerts-dropdown-menu-item`}
            disabledReasons={disabledReasons}
        >
            <IconWithCount count={alerts?.length} showZero={false}>
                <IconWarning />
            </IconWithCount>
            {alertsLabel}
        </ButtonPrimitive>
    )
}
