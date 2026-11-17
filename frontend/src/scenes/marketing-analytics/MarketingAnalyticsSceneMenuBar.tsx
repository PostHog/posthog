import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconComment, IconDocument, IconGear } from '@posthog/icons'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'marketing-analytics'
const MARKETING_ANALYTICS_DOCS_URL = 'https://posthog.com/docs/web-analytics/marketing-analytics'

export function MarketingAnalyticsSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <MarketingAnalyticsSceneMenuBarInner /> : null
}

function MarketingAnalyticsSceneMenuBarInner(): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            id: `${RESOURCE_TYPE}-menubar-settings`,
            label: 'Settings',
            icon: <IconGear />,
            onSelect: () => router.actions.push(urls.settings('environment-marketing-analytics', 'marketing-settings')),
            // pinned: data-attr values are wire strings
            pinned: { order: 2, variant: 'secondary', dataAttr: 'marketing-analytics-settings-button' },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-send-feedback`,
            label: 'Send feedback',
            icon: <IconComment />,
            opensFloatingUi: true,
            onSelect: () => openSupportForm({ kind: 'feedback', isEmailFormOpen: true }),
            pinned: { order: 1, variant: 'secondary' },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-documentation`,
            label: 'Documentation',
            icon: <IconDocument />,
            onSelect: () => window.open(MARKETING_ANALYTICS_DOCS_URL, '_blank', 'noopener,noreferrer'),
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
