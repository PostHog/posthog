/**
 * Demo Survey Data Generator
 *
 * Generates highly realistic survey response data to show customers exactly how their
 * survey results will look.
 */
import { dayjs } from 'lib/dayjs'
import { calculateSurveyRates } from 'scenes/surveys/utils'

import {
    ResponsesByQuestion,
    Survey,
    SurveyEventName,
    SurveyQuestion,
    SurveyQuestionType,
    SurveyRates,
    SurveyRawResults,
    SurveyResponseRow,
    SurveyStats,
} from '~/types'

import { NewSurvey, SURVEY_RATING_SCALE } from '../constants'
import { processResultsForSurveyQuestions } from '../surveyLogic'

// Demo configuration constants
export const DEMO_CONFIG = {
    // Response distributions for realistic data
    NPS_DETRACTORS_RATE: 0.2, // 20% detractors (0-6)
    NPS_PASSIVES_RATE: 0.15, // 15% passives (7-8)
    // Remaining 65% are promoters (9-10)

    // Single choice preferences
    FIRST_CHOICE_WEIGHT: 0.4, // First option often more popular
    OTHER_CHOICE_WEIGHT: 0.1, // "Other" options less common

    // Multiple choice behavior
    MIN_SELECTIONS: 1,
    MAX_SELECTIONS: 3,
    OPEN_CHOICE_PROBABILITY: 0.15, // 15% chance to select "Other"

    // Timeline settings
    RESPONSE_DAYS_RANGE: 30, // Responses over last 30 days
    DEFAULT_RESPONSE_COUNT: 76,

    // Survey stats ranges
    BASE_SHOWN_MIN: 120,
    BASE_SHOWN_MAX: 170,
    RESPONSE_RATE_MIN: 0.6,
    RESPONSE_RATE_MAX: 0.85,
    DISMISSAL_RATE_MIN: 0.1,
    DISMISSAL_RATE_MAX: 0.25,
} as const

// Sample user data for realistic responses
const SAMPLE_USERS = [
    { distinctId: 'user_001', name: 'Sarah Chen', email: 'sarah@company.com', role: 'Product Manager' },
    { distinctId: 'user_002', name: 'Alex Rodriguez', email: 'alex@startup.io', role: 'Designer' },
    { distinctId: 'user_003', name: 'Emma Thompson', email: 'emma@agency.co', role: 'Developer' },
    { distinctId: 'user_004', name: 'James Wilson', email: 'james@corp.com', role: 'Marketing Lead' },
    { distinctId: 'user_005', name: 'Priya Patel', email: 'priya@tech.com', role: 'Data Analyst' },
    { distinctId: 'user_006', name: 'Michael Brown', email: 'mike@consulting.com', role: 'Consultant' },
    { distinctId: 'user_007', name: 'Lisa Wang', email: 'lisa@fintech.io', role: 'Engineering Manager' },
    { distinctId: 'user_008', name: 'David Kim', email: 'david@media.com', role: 'Content Creator' },
    { distinctId: 'user_009', name: 'Nina Kowalski', email: 'nina@healthcare.org', role: 'Researcher' },
    { distinctId: 'user_010', name: 'Ryan Murphy', email: 'ryan@education.edu', role: 'Teacher' },
]

// Sample responses for different question types
const OPEN_RESPONSES = {
    feedback: [
        'Love the new dashboard! The analytics are much clearer now.',
        'The interface could be more intuitive. Sometimes I get lost in the navigation.',
        'Great product overall, but loading times could be faster.',
        'Amazing customer support team! They helped me resolve my issue quickly.',
        'The mobile app needs work - it feels clunky compared to the web version.',
        'Pricing is reasonable for the value provided. Very satisfied.',
        'Would love to see more integrations with other tools we use.',
        'The onboarding process was smooth and helpful.',
        'Some features are hard to find. Maybe reorganize the menu?',
        'Excellent reporting capabilities. Saves me hours of work.',
        'The search functionality could be improved.',
        'Love the real-time collaboration features!',
        'Documentation could be more comprehensive.',
        'The API is well-designed and easy to use.',
        'Would appreciate dark mode support.',
    ],
    improvement: [
        'Better search and filtering options',
        'More customization for dashboards',
        'Faster loading times',
        'Mobile app improvements',
        'More integration options',
        'Better notification system',
        'Improved user interface',
        'More detailed analytics',
        'Better documentation',
        'Enhanced security features',
        'Bulk operations support',
        'Advanced export options',
        'Team collaboration tools',
        'Automation features',
        'Performance optimizations',
    ],
    experience: [
        'Smooth and intuitive overall',
        'Had some initial learning curve but good now',
        'Very positive, exceeded expectations',
        'Mixed - some great features, some frustrations',
        'Excellent, would recommend to others',
        'Good but room for improvement',
        'Outstanding customer service experience',
        'The setup process was straightforward',
        'Love the clean, modern interface',
        'Sometimes slow but generally reliable',
    ],
}

function getRandomElement<T>(array: T[]): T {
    return array[Math.floor(Math.random() * array.length)]
}

function getRandomElements<T>(array: T[], minCount: number = 1, maxCount?: number): T[] {
    const max = maxCount || Math.min(array.length, 3)
    const count = Math.floor(Math.random() * (max - minCount + 1)) + minCount
    const shuffled = [...array].sort(() => 0.5 - Math.random())
    return shuffled.slice(0, count)
}

function generateOpenResponse(question: SurveyQuestion): string {
    const questionText = question.question.toLowerCase()

    if (questionText.includes('improve') || questionText.includes('better')) {
        return getRandomElement(OPEN_RESPONSES.improvement)
    }
    if (questionText.includes('experience') || questionText.includes('feel')) {
        return getRandomElement(OPEN_RESPONSES.experience)
    }
    return getRandomElement(OPEN_RESPONSES.feedback)
}

function generateRatingResponse(question: SurveyQuestion): string {
    const ratingQuestion = question as any // TODO: Improve typing for rating questions
    const isNPS = ratingQuestion.scale === SURVEY_RATING_SCALE.NPS_10_POINT

    if (isNPS) {
        // NPS distribution based on industry averages
        const rand = Math.random()
        if (rand < DEMO_CONFIG.NPS_DETRACTORS_RATE) {
            return String(Math.floor(Math.random() * 7)) // 0-6 (detractors)
        }
        if (rand < DEMO_CONFIG.NPS_DETRACTORS_RATE + DEMO_CONFIG.NPS_PASSIVES_RATE) {
            return String(7 + Math.floor(Math.random() * 2)) // 7-8 (passives)
        }
        return String(9 + Math.floor(Math.random() * 2)) // 9-10 (promoters)
    }

    // Regular rating scales tend to skew positive in real user feedback
    const scale = ratingQuestion.scale || 5
    const rand = Math.random()

    // Distribution: 10% very low, 10% low, 25% medium, 30% high, 25% very high
    if (rand < 0.1) {
        return '1'
    }
    if (rand < 0.2) {
        return '2'
    }
    if (rand < 0.35) {
        return String(Math.min(3, scale))
    }
    if (rand < 0.65) {
        return String(Math.min(4, scale))
    }
    return String(scale)
}

function generateSingleChoiceResponse(question: SurveyQuestion): string {
    const choices = (question as any).choices || []
    if (choices.length === 0) {
        return ''
    }

    // Weight responses based on typical user behavior patterns
    const hasOpenChoice = (question as any).hasOpenChoice
    const weights = choices.map((_: any, index: number) => {
        if (index === 0) {
            return DEMO_CONFIG.FIRST_CHOICE_WEIGHT // First choice often more popular
        }
        if (index === choices.length - 1 && hasOpenChoice) {
            return DEMO_CONFIG.OTHER_CHOICE_WEIGHT // "Other" less common
        }
        return 0.5 / (choices.length - (hasOpenChoice ? 2 : 1))
    })

    const totalWeight = weights.reduce((sum: number, weight: number) => sum + weight, 0)
    let random = Math.random() * totalWeight

    for (let i = 0; i < choices.length; i++) {
        random -= weights[i]
        if (random <= 0) {
            // If it's the open choice, add some custom text
            if (i === choices.length - 1 && (question as any).hasOpenChoice) {
                const customResponses = [
                    'API improvements',
                    'Better performance',
                    'Custom integrations',
                    'Team features',
                    'Security enhancements',
                ]
                return getRandomElement(customResponses)
            }
            return choices[i]
        }
    }

    return choices[0]
}

function generateMultipleChoiceResponse(question: SurveyQuestion): string[] {
    const choices = (question as any).choices || []
    if (choices.length === 0) {
        return []
    }

    // For multiple choice, users typically select 1-3 options
    const hasOpenChoice = (question as any).hasOpenChoice
    const availableChoices = hasOpenChoice ? choices.slice(0, -1) : choices
    const selectedChoices = getRandomElements(
        availableChoices,
        DEMO_CONFIG.MIN_SELECTIONS,
        Math.min(DEMO_CONFIG.MAX_SELECTIONS, availableChoices.length)
    ) as string[]

    // Sometimes add the open choice
    if (hasOpenChoice && Math.random() < DEMO_CONFIG.OPEN_CHOICE_PROBABILITY) {
        const customResponses = [
            'Better mobile support',
            'Advanced analytics',
            'Custom workflows',
            'Integration features',
            'Performance improvements',
        ]
        selectedChoices.push(getRandomElement(customResponses))
    }

    return selectedChoices
}

function generatePersonProperties(user: (typeof SAMPLE_USERS)[0]): string {
    return JSON.stringify({
        name: user.name,
        email: user.email,
        role: user.role,
        company_size: getRandomElement(['1-10', '11-50', '51-200', '201-1000', '1000+']),
        plan: getRandomElement(['free', 'pro', 'enterprise']),
        signup_date: dayjs()
            .subtract(Math.floor(Math.random() * 365), 'days')
            .toISOString(),
    })
}

function generateTimestamp(): string {
    // Generate timestamps over the configured time range for realistic distribution
    const daysAgo = Math.floor(Math.random() * DEMO_CONFIG.RESPONSE_DAYS_RANGE)
    const hoursAgo = Math.floor(Math.random() * 24)
    const minutesAgo = Math.floor(Math.random() * 60)

    return dayjs().subtract(daysAgo, 'days').subtract(hoursAgo, 'hours').subtract(minutesAgo, 'minutes').toISOString()
}

export function generateDemoSurveyResults(
    survey: Survey | NewSurvey,
    responseCount: number = DEMO_CONFIG.DEFAULT_RESPONSE_COUNT
): SurveyRawResults {
    const results: SurveyRawResults = []

    // Ensure we have a good distribution of users
    const selectedUsers =
        responseCount <= SAMPLE_USERS.length
            ? SAMPLE_USERS.slice(0, responseCount)
            : Array.from({ length: responseCount }, (_, i) => SAMPLE_USERS[i % SAMPLE_USERS.length])

    for (let i = 0; i < responseCount; i++) {
        const user = selectedUsers[i]
        const row: SurveyResponseRow = []

        // Generate response for each question
        survey.questions.forEach((question) => {
            if (question.type === SurveyQuestionType.Link) {
                // Link questions don't have responses
                return
            }

            switch (question.type) {
                case SurveyQuestionType.Open:
                    row.push(generateOpenResponse(question))
                    break
                case SurveyQuestionType.Rating:
                    row.push(generateRatingResponse(question))
                    break
                case SurveyQuestionType.SingleChoice:
                    row.push(generateSingleChoiceResponse(question))
                    break
                case SurveyQuestionType.MultipleChoice:
                    row.push(generateMultipleChoiceResponse(question))
                    break
            }
        })

        // Add person properties, distinct_id, and timestamp
        row.push(generatePersonProperties(user))
        row.push(user.distinctId)
        row.push(generateTimestamp())

        results.push(row)
    }

    // Sort by timestamp (newest first)
    results.sort((a: SurveyResponseRow, b: SurveyResponseRow) => {
        const timestampA = a[a.length - 1] as string
        const timestampB = b[b.length - 1] as string
        return dayjs(timestampB).valueOf() - dayjs(timestampA).valueOf()
    })

    return results
}

export function generateDemoSurveyStats(): SurveyStats {
    // Generate realistic stats for the demo based on industry benchmarks
    const baseShown =
        DEMO_CONFIG.BASE_SHOWN_MIN +
        Math.floor(Math.random() * (DEMO_CONFIG.BASE_SHOWN_MAX - DEMO_CONFIG.BASE_SHOWN_MIN))
    const responseRate =
        DEMO_CONFIG.RESPONSE_RATE_MIN + Math.random() * (DEMO_CONFIG.RESPONSE_RATE_MAX - DEMO_CONFIG.RESPONSE_RATE_MIN)
    const dismissalRate =
        DEMO_CONFIG.DISMISSAL_RATE_MIN +
        Math.random() * (DEMO_CONFIG.DISMISSAL_RATE_MAX - DEMO_CONFIG.DISMISSAL_RATE_MIN)

    const sent = Math.floor(baseShown * responseRate)
    const dismissed = Math.floor(baseShown * dismissalRate)

    return {
        [SurveyEventName.SENT]: {
            total_count: sent,
            unique_persons: sent,
            total_count_only_seen: 0,
            unique_persons_only_seen: 0,
            first_seen: null,
            last_seen: null,
        },
        [SurveyEventName.SHOWN]: {
            total_count: baseShown,
            unique_persons: baseShown,
            total_count_only_seen: 0,
            unique_persons_only_seen: 0,
            first_seen: null,
            last_seen: null,
        },
        [SurveyEventName.DISMISSED]: {
            total_count: dismissed,
            unique_persons: dismissed,
            total_count_only_seen: 0,
            unique_persons_only_seen: 0,
            first_seen: null,
            last_seen: null,
        },
    }
}

export function getDemoDataForSurvey(survey: Survey | NewSurvey): {
    demoStats: ReturnType<typeof generateDemoSurveyStats>
    demoResults: SurveyRawResults
    demoProcessedResults: ResponsesByQuestion
    responseCount: number
    demoRates: SurveyRates
} {
    const demoStats = generateDemoSurveyStats()
    const demoRates = calculateSurveyRates(demoStats)
    const demoResponseCount = demoStats[SurveyEventName.SENT].total_count
    const demoResults = generateDemoSurveyResults(survey, demoResponseCount)
    const demoProcessedResults = processResultsForSurveyQuestions(survey.questions, demoResults)

    return {
        demoStats: demoStats,
        demoResults: demoResults,
        demoProcessedResults: demoProcessedResults,
        responseCount: demoStats[SurveyEventName.SENT].total_count,
        demoRates,
    }
}
