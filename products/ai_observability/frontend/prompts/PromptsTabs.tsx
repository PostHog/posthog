import { LemonTabs } from '@posthog/lemon-ui'

import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export function PromptsTabs({ activeTab }: { activeTab: 'prompts' | 'playground' }): JSX.Element {
    const playgroundDisabledReason = getProductAccessDisabledReason({
        sceneKey: Scene.AIObservabilityPlayground,
        displayLabel: 'Playground',
    })

    return (
        <LemonTabs
            activeKey={activeTab}
            data-attr="prompts-tabs"
            sceneInset
            tabs={[
                {
                    key: 'prompts',
                    label: 'Prompts',
                    link: urls.aiObservabilityPrompts(),
                    'data-attr': 'prompts-tab',
                },
                {
                    key: 'playground',
                    label: 'Playground',
                    // LemonTabs still renders the link of a disabled tab, so a click would open the Access denied page.
                    link: playgroundDisabledReason ? undefined : urls.aiObservabilityPlayground(),
                    disabledReason: playgroundDisabledReason,
                    'data-attr': 'prompts-playground-tab',
                },
            ]}
        />
    )
}
