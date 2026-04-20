import { useActions } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconMessage } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SURVEY_CREATED_SOURCE } from 'scenes/surveys/constants'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { FeatureFlagType } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagsTab } from './featureFlagsLogic'

export function UserFeedbackSection({
    featureFlag,
    onGetFeedback,
}: {
    featureFlag: FeatureFlagType
    onGetFeedback: () => void
}): JSX.Element {
    const { setActiveTab } = useActions(featureFlagLogic)
    const { reportUserFeedbackButtonClicked } = useActions(eventUsageLogic)
    const [responseCounts, setResponseCounts] = useState<Record<string, number>>({})

    const surveys = useMemo(() => featureFlag.surveys || [], [featureFlag.surveys])

    useEffect(() => {
        if (surveys.length > 0) {
            const surveyIds = surveys.map((s) => s.id).join(',')
            api.surveys.getResponsesCount(surveyIds).then(setResponseCounts)
        }
    }, [surveys])

    const totalResponses = surveys.reduce((sum, s) => sum + (responseCounts[s.id] || 0), 0)

    const description = 'Gather feedback from users who see this feature flag.'
    let buttonText = 'Get feedback'
    let buttonAction = (): void => onGetFeedback()

    if (surveys.length > 0) {
        if (totalResponses === 0) {
            buttonText = 'Review survey'
        } else {
            buttonText = `Review ${totalResponses} response${totalResponses !== 1 ? 's' : ''}`
        }
        buttonAction = () => setActiveTab(FeatureFlagsTab.FEEDBACK)
    }

    const handleClick = (): void => {
        reportUserFeedbackButtonClicked(SURVEY_CREATED_SOURCE.FEATURE_FLAGS, {
            existingSurvey: surveys.length > 0,
        })

        buttonAction()
    }

    return (
        <SceneSection title="User feedback" description={description}>
            <div className="inline-block">
                <LemonButton onClick={handleClick} type="secondary" size="small" icon={<IconMessage />}>
                    {buttonText}
                </LemonButton>
            </div>
        </SceneSection>
    )
}
