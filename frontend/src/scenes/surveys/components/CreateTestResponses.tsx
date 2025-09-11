import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconTestTube } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyIdBasedResponseKey } from 'scenes/surveys/utils'

import { SurveyEventName, SurveyEventProperties, SurveyQuestionType } from '~/types'

const RESPONSE_GENERATION_DELAY_MS = 100
const STATS_REFRESH_DELAY_MS = 2000
const GIBBERISH_RESPONSES = [
    'asdf qwerty lorem ipsum dolor sit amet',
    'xyz123 random text here blah',
    'qwertyuiop asdfghjkl zxcvbnm',
    'Lorem ipsum dolor consectetur adipiscing',
    'Random gibberish text asdfsadfsadf',
    'kjhgfdsasdfghjklmnbvcxz qwerty',
    'test test test 123 xyz abc',
    'aaaaaaaaa bbbbbbb cccccc ddddd',
    'random string of characters here',
    'gibberish response text 9999',
    'zxcvbnmqwertyuiopasdfghjkl',
    'nonsense text goes here now',
    'blah blah blah random words',
    'test response gibberish text',
    'qwerty keyboard random text',
]

const QUALITY_RESPONSES = [
    'The interface could be more intuitive, especially the navigation menu',
    'Love the new dashboard features! Much easier to find what I need',
    'Performance has improved significantly since the last update',
    'Would be great to have more customization options for the widgets',
    "The mobile app needs work - it's quite slow on my device",
    'Excellent customer support team, very responsive and helpful',
    'The onboarding process was smooth and well-designed',
    'More integrations with popular tools would be fantastic',
    'The reporting features are comprehensive and useful',
    'Sometimes the UI feels cluttered with too many options',
    'Great product overall, has saved us a lot of time',
    'The search functionality could be more accurate',
    'Documentation is thorough and easy to follow',
    'Would love to see dark mode option added soon',
    'The pricing is fair for the value we get',
    'Export functionality works well and is very convenient',
    'Loading times could be faster for large datasets',
    'The collaboration features are exactly what we needed',
    'User permissions system is flexible and secure',
    'The analytics insights have helped improve our business',
    'The notification system is too aggressive - too many emails',
    'Really appreciate the keyboard shortcuts, makes workflow much faster',
    'The drag and drop functionality works perfectly',
    'Would be nice to have bulk editing capabilities',
    'The color scheme is pleasant and easy on the eyes',
    'API documentation could use more examples',
    'Love the real-time collaboration features',
    'The filtering options are powerful but could be simplified',
    'Mobile responsiveness has room for improvement',
    'The backup and restore process is reliable',
    'Would benefit from more granular access controls',
    'The data visualization tools are impressive',
    'Sometimes the auto-save feature is too slow',
    'The template library saves us tons of time',
    'Error messages could be more descriptive',
    'The recent updates have made everything more stable',
    'Would love to see more chart types available',
    'The user interface is clean and professional',
    'Import functionality works well with various file formats',
    'The learning curve is reasonable for new users',
    'Performance monitoring dashboard is very helpful',
    'Would appreciate more tutorial videos',
    'The comment and feedback system works great',
    'Sometimes the search results are not relevant',
    'The automated workflows have streamlined our processes',
    'Need better support for multiple languages',
    'The calendar integration works seamlessly',
    'Would be useful to have more export formats',
    'The security features give us peace of mind',
    'The pricing tiers make sense for different team sizes',
    'Load balancing seems to work well during peak hours',
    'The audit trail feature is exactly what we needed',
    'Would love to see more keyboard navigation options',
    'The responsive design works great on tablets',
    'Sometimes the UI freezes with large amounts of data',
    'The plugin ecosystem is robust and well-maintained',
    'Would benefit from better offline functionality',
    'The dashboard customization options are excellent',
    'The data import wizard is intuitive and helpful',
    'Would appreciate more granular notification settings',
    'The version control features work as expected',
    'The user onboarding flow could be more interactive',
    'Performance is consistent across different browsers',
    'Would love to see more automation capabilities',
    'The help documentation is comprehensive and searchable',
    'The file organization system is logical and efficient',
    'Sometimes the interface feels slow during peak usage',
    'The integration with third-party tools is seamless',
    'Would benefit from more advanced filtering options',
    'The data backup process is transparent and reliable',
    'The user feedback collection system works well',
    'Would appreciate more customizable dashboard widgets',
]

export function CreateTestResponses(): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const [isGenerating, setIsGenerating] = useState(false)
    const [lastGenerated, setLastGenerated] = useState<{ count: number; type: string } | null>(null)
    const { loadSurveyBaseStats } = useActions(surveyLogic)

    const isDev =
        (typeof process !== 'undefined' && process.env?.NODE_ENV === 'development') ||
        window.location.hostname.includes('localhost') ||
        window.location.hostname.includes('127.0.0.1')

    if (
        !isDev ||
        !survey.start_date ||
        survey.questions.length !== 1 ||
        survey.questions[0].type !== SurveyQuestionType.Open
    ) {
        return null
    }

    const generateResponses = async (responseType: 'realistic' | 'gibberish', count: number = 10): Promise<void> => {
        setIsGenerating(true)

        try {
            const responses = responseType === 'realistic' ? QUALITY_RESPONSES : GIBBERISH_RESPONSES
            const openQuestions = survey.questions.filter((q) => q.type === SurveyQuestionType.Open)

            if (openQuestions.length === 0) {
                alert('No open text questions found in this survey')
                return
            }

            for (let i = 0; i < count; i++) {
                posthog.capture(SurveyEventName.SHOWN, {
                    [SurveyEventProperties.SURVEY_ID]: survey.id,
                })

                const properties: Record<string, any> = {
                    [SurveyEventProperties.SURVEY_ID]: survey.id,
                    [SurveyEventProperties.SURVEY_COMPLETED]: true,
                    $survey_name: survey.name,
                    $survey_questions: [],
                }

                openQuestions.forEach((question) => {
                    const randomResponse = responses[Math.floor(Math.random() * responses.length)]
                    properties[getSurveyIdBasedResponseKey(question.id!)] = randomResponse
                    properties.$survey_questions.push({
                        id: question.id,
                        question: question.question,
                        response: randomResponse,
                    })
                })

                posthog.capture(SurveyEventName.SENT, properties)

                if (i < count - 1) {
                    await new Promise((resolve) => setTimeout(resolve, RESPONSE_GENERATION_DELAY_MS))
                }
            }

            setLastGenerated({ count, type: responseType })

            setTimeout(() => {
                loadSurveyBaseStats()
            }, STATS_REFRESH_DELAY_MS)
        } catch (error) {
            console.error('Error generating demo responses:', error)
            alert('Error generating responses. Check console for details.')
        } finally {
            setIsGenerating(false)
        }
    }

    return (
        <div className="flex items-center gap-2">
            {lastGenerated && (
                <span className="text-xs text-muted mr-2">
                    ✅ Generated {lastGenerated.count} {lastGenerated.type} responses
                </span>
            )}

            <LemonButton
                icon={<IconTestTube />}
                type="secondary"
                size="small"
                onClick={() => generateResponses('realistic', 10)}
                loading={isGenerating}
                tooltip="Generate 10 realistic demo responses for testing"
            >
                {isGenerating ? 'Generating...' : 'Demo Responses'}
            </LemonButton>

            <LemonButton
                type="secondary"
                size="small"
                onClick={() => generateResponses('gibberish', 10)}
                loading={isGenerating}
                tooltip="Generate 10 gibberish responses for testing edge cases"
            >
                {isGenerating ? 'Generating...' : 'Gibberish Responses'}
            </LemonButton>
        </div>
    )
}
