import { useActions, useValues } from 'kea'

import { IconMessage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { webAnalyticsLogic } from '../webAnalyticsLogic'

interface CreateSurveyButtonProps {
    value: string
}

export const CreateSurveyButton = ({ value }: CreateSurveyButtonProps): JSX.Element => {
    const { openSurveyModal } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.SURVEYS_WEB_ANALYTICS_CROSS_SELL]) {
        return <></>
    }

    if (!value || value === '') {
        return <></>
    }

    return (
        <LemonButton
            icon={<IconMessage />}
            type="tertiary"
            size="xsmall"
            tooltip="Survey users on this page"
            className="no-underline"
            onClick={(e: React.MouseEvent) => {
                e.stopPropagation()
                openSurveyModal(value)
                void addProductIntentForCrossSell({
                    from: ProductKey.WEB_ANALYTICS,
                    to: ProductKey.SURVEYS,
                    intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
                })
            }}
        />
    )
}
