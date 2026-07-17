import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { ProductKey } from '~/queries/schema/schema-general'

import { ProductCard } from './Quickstart'
import {
    QuickstartJourneyStep,
    QuickstartProduct,
    QuickstartTaskGuide,
    QuickstartToolCta,
    QuickstartToolLevel,
} from './quickstartLogic'

interface CardArgs {
    name: string
    bestFor: string
    description: string
    level: QuickstartToolLevel
    cta: QuickstartToolCta
    statValue: number
    statLabel: string
    stepsAchieved: number
    stepsTotal: number
    nextStep: string
    showDocs: boolean
}

const JOURNEY_LABELS = [
    'Install a PostHog SDK',
    'Capture your first event',
    'Deploy your instrumentation to production',
    'Capture your first custom event',
    'Track 5+ distinct custom events',
    'Identify your users',
    'Set up an alert',
]

const STORY_GUIDE: QuickstartTaskGuide = {
    description: 'Complete this task to improve the tool setup.',
    instructions: ['Open the relevant setup.', 'Follow the instructions.', 'Return after data arrives.'],
    action: 'setup',
    actionLabel: 'Open setup',
}

function buildJourney(achieved: number, total: number): QuickstartJourneyStep[] {
    return Array.from({ length: total }, (_, index) => ({
        key: `step-${index}`,
        label: JOURNEY_LABELS[index] ?? `Example step ${index + 1}`,
        kind: index < 2 ? ('activation' as const) : ('quality' as const),
        achieved: index < achieved,
        guide: STORY_GUIDE,
    }))
}

function buildProduct(args: CardArgs): QuickstartProduct {
    const journey = buildJourney(args.stepsAchieved, args.stepsTotal)
    const nextStep = args.nextStep
        ? { ...(journey.find((step) => !step.achieved) ?? journey[0]), label: args.nextStep }
        : null

    return {
        key: ProductKey.PRODUCT_ANALYTICS,
        name: args.name,
        description: args.description,
        icon: 'IconGraph',
        iconColor: 'blue',
        bestFor: args.bestFor,
        requiresEvents: true,
        url: '#',
        setupUrl: '#',
        docsUrl: args.showDocs ? 'https://posthog.com/docs' : undefined,
        status: {
            level: args.level,
            journey,
            nextStep,
            stat: args.statValue > 0 ? { value: args.statValue, label: args.statLabel } : null,
            cta: args.cta,
        },
    }
}

const meta: Meta<CardArgs> = {
    title: 'Scenes-App/Quickstart/Product card',
    parameters: {
        viewMode: 'story',
        mockDate: '2026-07-15',
    },
    decorators: [
        // The card mounts quickstartLogic, whose loaders fire on mount — keep them quiet
        mswDecorator({
            get: {
                '/api/environments/:team_id/logs/has_logs': { hasLogs: false },
                '/api/environments/:team_id/external_data_sources/': { results: [] },
                '/api/environments/:team_id/hog_flows/': { results: [] },
                '/api/environments/:team_id/error_tracking/symbol_sets/': { count: 0, results: [] },
                '/api/environments/:team_id/hog_functions/': { count: 0, results: [] },
                '/api/projects/:team_id/conversations/tickets/': { count: 0, results: [] },
                'https://posthog.com/rss.xml': () => new Response('', { status: 404 }),
            },
            post: {
                '/api/environments/:team_id/query': { results: [[]] },
            },
        }),
    ],
}
export default meta

const Template: StoryFn<CardArgs> = (args) => (
    <div className="max-w-100 p-4">
        <ProductCard product={buildProduct(args)} />
    </div>
)

/** Every knob of a card's status, to preview any state a tool can be in */
export const Playground: StoryObj<CardArgs> = {
    render: Template,
    args: {
        name: 'Product analytics',
        bestFor: 'understanding user behavior',
        description: 'See what users do in your app',
        level: 'live',
        cta: 'open',
        statValue: 53,
        statLabel: 'custom events',
        stepsAchieved: 4,
        stepsTotal: 6,
        nextStep: 'Track 5+ distinct custom events',
        showDocs: true,
    },
    argTypes: {
        level: { control: 'select', options: ['needs_setup', 'ready', 'live'] },
        cta: { control: 'select', options: ['install', 'enable', 'setup', 'open'] },
        stepsAchieved: { control: { type: 'number', min: 0, max: 7 } },
        stepsTotal: { control: { type: 'number', min: 1, max: 7 } },
    },
}

/** One card per representative state, for at-a-glance visual QA of the whole vocabulary */
export const AllStates: StoryObj = {
    render: () => {
        const states: Array<Partial<CardArgs> & { title: string }> = [
            {
                title: 'Needs setup, install pending',
                level: 'needs_setup',
                cta: 'install',
                statValue: 0,
                stepsAchieved: 0,
                stepsTotal: 6,
                nextStep: 'Install a PostHog SDK',
            },
            {
                title: 'Needs setup, one-click enable',
                level: 'needs_setup',
                cta: 'enable',
                statValue: 0,
                stepsAchieved: 1,
                stepsTotal: 5,
                nextStep: 'Turn on session recordings',
            },
            {
                title: 'Ready, waiting for first data',
                level: 'ready',
                cta: 'open',
                statValue: 0,
                stepsAchieved: 2,
                stepsTotal: 6,
                nextStep: 'Capture your first exception',
            },
            {
                title: 'Live, early quality',
                level: 'live',
                cta: 'open',
                statValue: 53,
                statLabel: 'custom events',
                stepsAchieved: 3,
                stepsTotal: 7,
                nextStep: 'Deploy your instrumentation to production',
            },
            {
                title: 'Live, secondary enable available',
                level: 'live',
                cta: 'enable',
                statValue: 42,
                statLabel: 'exceptions · 30d',
                stepsAchieved: 4,
                stepsTotal: 7,
                nextStep: 'Turn on exception autocapture for the web',
            },
            {
                title: 'Live, no current suggestion',
                level: 'live',
                cta: 'open',
                statValue: 4200,
                statLabel: 'tool calls · 30d',
                stepsAchieved: 5,
                stepsTotal: 5,
                nextStep: '',
            },
        ]
        return (
            <div className="grid grid-cols-2 xl:grid-cols-3 gap-4 p-4 max-w-300">
                {states.map(({ title, ...overrides }) => (
                    <div key={title} className="flex flex-col gap-2">
                        <div className="text-xs font-semibold text-secondary">{title}</div>
                        <ProductCard
                            product={buildProduct({
                                name: 'Product analytics',
                                bestFor: 'understanding user behavior',
                                description: 'See what users do in your app',
                                level: 'live',
                                cta: 'open',
                                statValue: 0,
                                statLabel: 'custom events',
                                stepsAchieved: 0,
                                stepsTotal: 5,
                                nextStep: '',
                                showDocs: true,
                                ...overrides,
                            })}
                        />
                    </div>
                ))}
            </div>
        )
    },
}
