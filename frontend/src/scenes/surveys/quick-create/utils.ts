import { SURVEY_CREATED_SOURCE } from '../constants'
import { QuickSurveyFormLogicProps } from './quickSurveyFormLogic'
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
    }
}
