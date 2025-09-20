import { DeepPartialMap, ValidationErrorType } from 'kea-forms'

import { NewSurvey } from 'scenes/surveys/constants'

import { Survey, SurveyAppearance } from '~/types'

export interface CommonProps {
    survey: NewSurvey | Survey
    onAppearanceChange: (appearance: Partial<SurveyAppearance>) => void
    validationErrors?: DeepPartialMap<SurveyAppearance, ValidationErrorType> | null
    hasRatingButtons: boolean
    hasPlaceholderText: boolean
    selectedPageIndex?: number
    setSelectedPageIndex?: (pageIndex: number) => void
}

export interface CustomizationProps extends CommonProps {
    hasBranchingLogic: boolean
    deleteBranchingLogic?: () => void
}
