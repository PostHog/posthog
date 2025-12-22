import { SurveyQuestionType } from 'posthog-js'

import { EventsNode } from '~/queries/schema/schema-general'
import { SurveyMatchType } from '~/types'

import { SURVEY_CREATED_SOURCE, defaultSurveyAppearance } from '../constants'
import { toSurveyEvent } from '../utils/opportunityDetection'
import {
    DEFAULT_RATING_LOWER_LABEL,
    DEFAULT_RATING_UPPER_LABEL,
    QuickSurveyFormLogicProps,
} from './quickSurveyFormLogic'
import { QuickSurveyContext, QuickSurveyType } from './types'

export const buildLogicProps = (context: QuickSurveyContext): Omit<QuickSurveyFormLogicProps, 'onSuccess'> => {
    const randomId = Math.random().toString(36).substring(2, 8)

    switch (context.type) {
        case QuickSurveyType.FEATURE_FLAG:
            return {
                key: `flag-${context.flag.id}`,
                contextType: context.type,
                source: SURVEY_CREATED_SOURCE.FEATURE_FLAGS,
                defaults: {
                    name: `${context.flag.name || context.flag.key}${context.initialVariantKey ? ` (${context.initialVariantKey})` : ''} - Quick feedback ${randomId}`,
                    question: `You're trying our latest new feature. What do you think?`,
                    linkedFlagId: context.flag.id,
                    conditions: {
                        actions: null,
                        events: { values: [] },
                        ...(context.initialVariantKey ? { linkedFlagVariant: context.initialVariantKey } : {}),
                    },
                },
            }

        case QuickSurveyType.FUNNEL:
            return {
                key: `funnel-${context.funnel.insightName}`,
                contextType: context.type,
                source: SURVEY_CREATED_SOURCE.INSIGHT_CROSS_SELL,
                defaults: {
                    name: `${context.funnel.insightName} - Quick feedback ${randomId}`,
                    question: `We noticed you started but didn't complete this action. What stopped you?`,
                    conditions: {
                        actions: null,
                        events: {
                            values: [toSurveyEvent(context.funnel.steps[0] as EventsNode)],
                        },
                        cancelEvents: {
                            values: [toSurveyEvent(context.funnel.steps[1] as EventsNode)],
                        },
                    },
                    appearance: {
                        ...defaultSurveyAppearance,
                        surveyPopupDelaySeconds: 15,
                    },
                },
            }

        case QuickSurveyType.EXPERIMENT:
            return {
                key: `experiment-${context.experiment.id}`,
                contextType: context.type,
                source: SURVEY_CREATED_SOURCE.EXPERIMENTS,
                defaults: {
                    name: `${context.experiment.name} - Quick feedback ${randomId}`,
                    question: 'This update?',
                    questionType: SurveyQuestionType.Rating,
                    ratingLowerBound: DEFAULT_RATING_LOWER_LABEL,
                    ratingUpperBound: DEFAULT_RATING_UPPER_LABEL,
                    linkedFlagId: context.experiment.feature_flag?.id,
                },
            }

        case QuickSurveyType.ANNOUNCEMENT:
            return {
                key: `announcement-quick-survey-${randomId}`,
                contextType: context.type,
                source: SURVEY_CREATED_SOURCE.SURVEY_FORM,
                defaults: {
                    questionType: SurveyQuestionType.Link,
                    name: `Announcement (${randomId})`,
                    question: 'Hog mode is now available!',
                    description: 'You can never have too many hedgehogs.',
                    buttonText: 'Check it out 👉',
                },
            }

        case QuickSurveyType.ERROR_TRACKING:
            return {
                key: `error-tracking-${context.exceptionType}-${randomId}`,
                contextType: context.type,
                source: SURVEY_CREATED_SOURCE.ERROR_TRACKING,
                defaults: {
                    name: `${context.exceptionType} feedback (${randomId})`,
                    question: 'Looks like we hit a snag - how disruptive was this?',
                    questionType: SurveyQuestionType.Rating,
                    scaleType: 'number',
                    ratingLowerBound: 'Minor glitch',
                    ratingUpperBound: "Can't continue",
                    followUpEnabled: true,
                    followUpQuestion: 'What were you trying to do?',
                    conditions: {
                        actions: null,
                        events: {
                            values: [
                                {
                                    name: '$exception',
                                    propertyFilters: {
                                        $exception_types: { values: [context.exceptionType], operator: 'exact' },
                                        ...(context.exceptionMessage
                                            ? {
                                                  $exception_values: {
                                                      values: [context.exceptionMessage],
                                                      operator: 'icontains',
                                                  },
                                              }
                                            : {}),
                                    },
                                },
                            ],
                        },
                    },
                },
            }

        case QuickSurveyType.WEB_PATH:
            return {
                key: `web-path-${context.path}-${randomId}`,
                contextType: context.type,
                source: SURVEY_CREATED_SOURCE.WEB_ANALYTICS,
                defaults: {
                    name: `Survey users on ${context.path} (${randomId})`,
                    question: 'How was your experience on this page?',
                    questionType: SurveyQuestionType.Rating,
                    scaleType: 'emoji',
                    ratingLowerBound: 'Terrible',
                    ratingUpperBound: 'Amazing',
                    followUpEnabled: true,
                    followUpQuestion: 'What could we improve?',
                    conditions: {
                        actions: null,
                        events: null,
                        url: context.path,
                        urlMatchType: SurveyMatchType.Contains,
                    },
                    appearance: {
                        ...defaultSurveyAppearance,
                        surveyPopupDelaySeconds: 15,
                    },
                },
            }
    }
}
