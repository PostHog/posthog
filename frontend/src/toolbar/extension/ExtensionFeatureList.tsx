import { useActions } from 'kea'

import { IconExternal } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { PAGE_TOOLS } from './extensionPageTools'
import { extensionPanelLogic } from './extensionPanelLogic'
import { usePageToolDisabledReason } from './usePageToolDisabledReason'

export function ExtensionFeatureList({ origin }: { origin: string }): JSX.Element {
    const { openFeature } = useActions(extensionPanelLogic)
    const disabledReason = usePageToolDisabledReason()

    return (
        <div className="flex flex-col gap-1">
            <div className="text-secondary text-xs">Open in PostHog for {new URL(origin).host}</div>
            {PAGE_TOOLS.map(({ feature, ...tool }) =>
                feature ? (
                    <LemonButton
                        key={feature.key}
                        fullWidth
                        icon={tool.icon}
                        sideIcon={<IconExternal />}
                        disabledReason={disabledReason({ ...tool, feature })}
                        tooltip={`${tool.description}. Opens in PostHog.`}
                        onClick={() => openFeature(feature.key, feature.path)}
                        data-attr={`toolbar-extension-feature-${feature.key}`}
                    >
                        {tool.label}
                    </LemonButton>
                ) : null
            )}
        </div>
    )
}
