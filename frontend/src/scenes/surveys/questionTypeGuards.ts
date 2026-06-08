import {
    LinkSurveyQuestion,
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    SliderSurveyQuestion,
    SurveyQuestion,
    SurveyQuestionType,
} from '~/types'

export function isChoiceQuestion(question: SurveyQuestion): question is MultipleSurveyQuestion {
    return question.type === SurveyQuestionType.SingleChoice || question.type === SurveyQuestionType.MultipleChoice
}

export function isRatingQuestion(question: SurveyQuestion): question is RatingSurveyQuestion {
    return question.type === SurveyQuestionType.Rating
}

export function isLinkQuestion(question: SurveyQuestion): question is LinkSurveyQuestion {
    return question.type === SurveyQuestionType.Link
}

export function isSliderQuestion(question: SurveyQuestion): question is SliderSurveyQuestion {
    return question.type === SurveyQuestionType.Slider
}
