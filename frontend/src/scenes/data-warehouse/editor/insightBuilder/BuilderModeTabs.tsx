import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { EditorMode, outputPaneLogic } from '../outputPaneLogic'
import { insightBuilderLogic } from './insightBuilderLogic'

export function BuilderModeTabs({ tabId }: { tabId: string }): JSX.Element {
    const { editorMode } = useValues(outputPaneLogic({ tabId }))
    const { setEditorMode } = useActions(outputPaneLogic({ tabId }))
    const { buildModeDisabledReason } = useValues(insightBuilderLogic({ tabId }))

    return (
        <LemonTabs
            size="small"
            activeKey={editorMode}
            onChange={(mode) => setEditorMode(mode as EditorMode)}
            barClassName="px-2 shrink-0 mb-0"
            tabs={[
                { key: EditorMode.Data, label: 'Data' },
                {
                    key: EditorMode.Build,
                    label: 'Build',
                    disabledReason: buildModeDisabledReason ?? undefined,
                    tooltip: buildModeDisabledReason ? undefined : 'Build an insight visually from your query results',
                },
            ]}
        />
    )
}
