import { useActions, useValues } from 'kea'

import { IconTrash, IconWarning } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { INTRO_SCREEN_TEXT_FIELDS } from './constants'
import { surveyLogic } from './surveyLogic'

export function SurveyEditIntroScreenHeader(): JSX.Element {
    const { survey, translationErrorsForField } = useValues(surveyLogic)
    const { setSurveyValue, setSelectedPageIndex } = useActions(surveyLogic)

    const errorCount = INTRO_SCREEN_TEXT_FIELDS.filter((field) => translationErrorsForField(-1, field)).length

    return (
        <div className="flex flex-row w-full items-center justify-between">
            <b>Intro screen</b>
            <div className="flex items-center gap-1">
                {errorCount > 0 && (
                    <Tooltip title={`${errorCount} translation validation issue${errorCount > 1 ? 's' : ''}`}>
                        <IconWarning className="text-warning" />
                    </Tooltip>
                )}
                <LemonButton
                    icon={<IconTrash />}
                    data-attr="delete-survey-intro-screen"
                    size="xsmall"
                    onClick={(e) => {
                        e.stopPropagation()
                        setSelectedPageIndex(0)
                        setSurveyValue('appearance', { ...survey.appearance, displayIntroScreen: false })
                    }}
                    tooltipPlacement="top-end"
                />
            </div>
        </div>
    )
}
