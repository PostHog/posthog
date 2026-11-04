import { useActions, useValues } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'

import { ElementClickStats } from 'lib/components/heatmaps/ElementClickStats'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'

import { SelectorQualityWarning } from '~/toolbar/shared/elements/SelectorQualityWarning'
import { urls } from '~/toolbar/shared/urls'

import { extensionActionsLogic } from '../../logics/panel/extensionActionsLogic'
import { extensionPageToolbarConnectionLogic } from '../../logics/panel/extensionPageToolbarConnectionLogic'
import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'

export function ExtensionInspectedElement(): JSX.Element | null {
    const { inspect, heatmap } = useValues(extensionPageToolbarConnectionLogic)
    const { sendCommand } = useActions(extensionPageToolbarConnectionLogic)
    const { newAction } = useActions(extensionActionsLogic)
    const { projectUrl } = useValues(extensionPanelLogic)
    const element = inspect?.element
    if (!element) {
        return null
    }
    const { actionStep, stats, actions } = element

    return (
        <div className="flex flex-col gap-2 border rounded p-2 text-xs">
            <div className="flex items-start gap-1">
                <div className="flex-1 min-w-0 flex flex-col gap-1">
                    <div className="font-semibold">{inspect.isSelected ? 'Selected element' : 'Hovered element'}</div>
                    <code className="break-all" translate="no">
                        {actionStep?.selector || `<${element.tagName}>`}
                    </code>
                    {actionStep?.text && <div className="text-secondary truncate">Text: {actionStep.text}</div>}
                    {actionStep?.href && (
                        <div className="text-secondary truncate" translate="no">
                            Link: {actionStep.href}
                        </div>
                    )}
                    <SelectorQualityWarning selector={actionStep?.selector} compact />
                </div>
                {inspect.isSelected && (
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        tooltip="Clear the selection"
                        onClick={() => sendCommand({ tool: 'inspect', command: { type: 'clear-selected-element' } })}
                        data-attr="toolbar-extension-clear-inspected-element"
                    />
                )}
            </div>
            {stats && (
                <ElementClickStats
                    count={stats.count}
                    totalCount={heatmap?.clickCount ?? 0}
                    rank={stats.rank}
                    clickCount={stats.clickCount}
                    rageclickCount={stats.rageclickCount}
                    deadclickCount={stats.deadclickCount}
                />
            )}
            <div className="flex flex-col gap-1">
                <div className="font-semibold">Actions ({actions.length})</div>
                {actions.length === 0 ? (
                    <div className="text-secondary">No actions include this element.</div>
                ) : (
                    actions.map((action) => (
                        <Link
                            key={action.id}
                            to={projectUrl(urls.action(action.id))}
                            target="_blank"
                            className="truncate"
                        >
                            {action.name || `Action ${action.id}`}
                        </Link>
                    ))
                )}
            </div>
            {inspect.isSelected && (
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={() => newAction(true)}
                    data-attr="toolbar-extension-create-action-from-element"
                >
                    Create action from this element
                </LemonButton>
            )}
        </div>
    )
}
