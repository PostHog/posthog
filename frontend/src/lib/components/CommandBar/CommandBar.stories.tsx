import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { BarStatus } from 'lib/components/CommandBar/types'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { CommandBar } from './CommandBar'

const SEARCH_RESULT = {
    results: [
        {
            type: 'insight',
            result_id: '3b7NrJXF',
            extra_fields: {
                name: '',
                description: '',
                derived_name: 'SQL query',
            },
        },
        {
            type: 'insight',
            result_id: 'U2W7bAq1',
            extra_fields: {
                name: '',
                description: '',
                derived_name: 'All events → All events user conversion rate',
            },
        },
        {
            type: 'feature_flag',
            result_id: '120',
            extra_fields: {
                key: 'person-on-events-enabled',
                name: 'person-on-events-enabled',
            },
        },
        {
            type: 'insight',
            result_id: '44fpCyF7',
            extra_fields: {
                name: '',
                description: '',
                derived_name: 'User lifecycle based on Pageview',
            },
        },
        {
            type: 'feature_flag',
            result_id: '150',
            extra_fields: {
                key: 'cs-dashboards',
                name: 'cs-dashboards',
            },
        },
        {
            type: 'notebook',
            result_id: 'b1ZyFO6K',
            extra_fields: {
                title: 'Notes 27/09',
                text_content: 'Notes 27/09\nasd\nas\nda\ns\nd\nlalala',
            },
        },
        {
            type: 'insight',
            result_id: 'Ap5YYl2H',
            extra_fields: {
                name: '',
                description: '',
                derived_name:
                    'Pageview count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count',
            },
        },
        {
            type: 'insight',
            result_id: '4Xaltnro',
            extra_fields: {
                name: '',
                description: '',
                derived_name: 'User paths based on page views and custom events',
            },
        },
        {
            type: 'insight',
            result_id: 'HUkkq7Au',
            extra_fields: {
                name: '',
                description: '',
                derived_name:
                    'Pageview count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count & All events count',
            },
        },
        {
            type: 'insight',
            result_id: 'hF5z02Iw',
            extra_fields: {
                name: '',
                description: '',
                derived_name: 'Pageview count & All events count',
            },
        },
        {
            type: 'feature_flag',
            result_id: '143',
            extra_fields: {
                key: 'high-frequency-batch-exports',
                name: 'high-frequency-batch-exports',
            },
        },
        {
            type: 'feature_flag',
            result_id: '126',
            extra_fields: {
                key: 'onboarding-v2-demo',
                name: 'onboarding-v2-demo',
            },
        },
        {
            type: 'feature_flag',
            result_id: '142',
            extra_fields: {
                key: 'web-analytics',
                name: 'web-analytics',
            },
        },
        {
            type: 'insight',
            result_id: '94r9bOyB',
            extra_fields: {
                name: '',
                description: '',
                derived_name: 'Pageview count & All events count',
            },
        },
        {
            type: 'dashboard',
            result_id: '1',
            extra_fields: {
                name: '🔑 Key metrics',
                description: 'Company overview.',
            },
        },
        {
            type: 'notebook',
            result_id: 'eq4n8PQY',
            extra_fields: {
                title: 'asd',
                text_content: 'asd',
            },
        },
        {
            type: 'insight',
            result_id: 'QcCPEk7d',
            extra_fields: {
                name: 'Daily unique visitors over time',
                description: null,
                derived_name: '$pageview unique users & All events count',
            },
        },
        {
            type: 'feature_flag',
            result_id: '133',
            extra_fields: {
                key: 'feedback-scene',
                name: 'feedback-scene',
            },
        },
        {
            type: 'insight',
            result_id: 'PWwez0ma',
            extra_fields: {
                name: 'Most popular pages',
                description: null,
                derived_name: null,
            },
        },
        {
            type: 'insight',
            result_id: 'HKTERZ40',
            extra_fields: {
                name: 'Feature Flag calls made by unique users per variant',
                description:
                    'Shows the number of unique user calls made on feature flag per variant with key: notebooks',
                derived_name: null,
            },
        },
        {
            type: 'feature_flag',
            result_id: '161',
            extra_fields: {
                key: 'console-recording-search',
                name: 'console-recording-search',
            },
        },
        {
            type: 'feature_flag',
            result_id: '134',
            extra_fields: {
                key: 'early-access-feature',
                name: 'early-access-feature',
            },
        },
        {
            type: 'insight',
            result_id: 'uE7xieYc',
            extra_fields: {
                name: '',
                description: '',
                derived_name: 'Pageview count',
            },
        },
        {
            type: 'feature_flag',
            result_id: '159',
            extra_fields: {
                key: 'surveys-multiple-questions',
                name: 'surveys-multiple-questions',
            },
        },
        {
            type: 'insight',
            result_id: 'AVPsaax4',
            extra_fields: {
                name: 'Monthly app revenue',
                description: null,
                derived_name: null,
            },
        },
    ],
    counts: {
        insight: 80,
        dashboard: 14,
        experiment: 1,
        feature_flag: 66,
        notebook: 2,
        action: 4,
        cohort: 3,
    },
}

const meta: Meta<typeof CommandBar> = {
    title: 'Components/Command Bar',
    component: CommandBar,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/search': SEARCH_RESULT,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotTargetSelector: '[data-attr="command-bar"]',
        },
        viewMode: 'story',
    },
}
export default meta

export function Search(): JSX.Element {
    const { setCommandBar } = useActions(commandBarLogic)

    useEffect(() => {
        setCommandBar(BarStatus.SHOW_SEARCH)
    }, [])

    return <CommandBar />
}

export function Actions(): JSX.Element {
    const { setCommandBar } = useActions(commandBarLogic)

    useEffect(() => {
        setCommandBar(BarStatus.SHOW_ACTIONS)
    }, [])

    return <CommandBar />
}

export function Shortcuts(): JSX.Element {
    const { setCommandBar } = useActions(commandBarLogic)

    useEffect(() => {
        setCommandBar(BarStatus.SHOW_SHORTCUTS)
    }, [])

    return <CommandBar />
}
