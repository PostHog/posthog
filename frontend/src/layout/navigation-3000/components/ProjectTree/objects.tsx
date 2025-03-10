import {
    IconDashboard,
    IconFeatures,
    IconGraph,
    IconMegaphone,
    IconMessage,
    IconNotebook,
    IconPlug,
    IconServer,
    IconSparkles,
    IconTarget,
    IconTestTube,
    IconToggle,
} from '@posthog/icons'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { FileSystemObject, FileSystemType } from '~/queries/schema/schema-general'

export const fileSystemObjects: Record<FileSystemType, FileSystemObject> = {
    aichat: {
        name: 'AI Chat',
        icon: <IconSparkles />,
        create: [
            {
                name: 'AI Chat',
                url: urls.max(),
            },
        ],
    },
    broadcast: {
        name: 'Broadcast',
        icon: <IconMegaphone />,
        create: [
            {
                name: 'AI Chat',
                url: urls.max(),
            },
        ],
    },
    feature_flag: {
        name: 'Feature Flag',
        icon: <IconToggle />,
        create: true,
    },
    feature: {
        name: 'Feature',
        icon: <IconFeatures />,
        create: true,
    },
    experiment: {
        name: 'Experiment',
        icon: <IconTestTube />,
        create: true,
    },
    insight: {
        name: 'Insight',
        icon: <IconGraph />,
        create: [
            {
                name: 'Insight/Trends',
            },
            {
                name: 'Insight/Funnels',
            },
            {
                name: 'Insight/Retention',
            },
            {
                name: 'Insight/Paths',
            },
            {
                name: 'Insight/Stickiness',
            },
        ],
    },
    notebook: {
        name: 'Notebook',
        icon: <IconNotebook />,
        create: true,
    },
    dashboard: {
        name: 'Dashboard',
        icon: <IconDashboard />,
        create: true,
    },
    repl: {
        name: 'Repl',
        icon: <IconTarget />,
        create: true,
    },
    survey: {
        name: 'Survey',
        icon: <IconMessage />,
        create: true,
    },
    sql: {
        name: 'SQL',
        icon: <IconServer />,
        create: true,
    },
    site_app: {
        name: 'Site App',
        icon: <IconPlug />,
        create: true,
    },
    destination: {
        name: 'Destination',
        icon: <IconPlug />,
        create: true,
    },
    transformation: {
        name: 'Transformation',
        icon: <IconPlug />,
        create: true,
    },
    source: {
        name: 'Source',
        icon: <IconPlug />,
        create: true,
    },
    folder: {
        name: 'Folder',
        icon: <IconChevronRight />,
        create: true,
    },
}
