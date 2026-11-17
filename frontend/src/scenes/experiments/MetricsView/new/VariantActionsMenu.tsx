import { IconEllipsis, IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { QuillVariantActionsMenu } from './QuillVariantActionsMenu'
import { type VariantActionsMenuProps, useVariantActions } from './useVariantActions'

export type { VariantActionsMenuProps } from './useVariantActions'

export function VariantActionsMenu(props: VariantActionsMenuProps): JSX.Element {
    const { trackMenuOpened, recordings, sqlActions } = useVariantActions(props)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillVariantActionsMenu {...props} />
    }

    return (
        <LemonMenu
            placement="bottom-start"
            onVisibilityChange={(visible) => {
                if (visible) {
                    trackMenuOpened()
                }
            }}
            items={[
                {
                    items: [
                        {
                            label: 'View recordings',
                            icon: <IconRewindPlay />,
                            'data-attr': 'experiment-variant-menu-recordings',
                            placement: 'right-start',
                            items: recordings.map((recording) => ({
                                label: recording.label,
                                tooltip: recording.tooltip,
                                disabledReason: recording.disabledReason,
                                to: recording.url,
                                'data-attr': recording.dataAttr,
                                onClick: recording.onClick,
                            })),
                        },
                    ],
                },
                {
                    items: sqlActions.map((action) => ({
                        label: action.label,
                        icon: action.icon,
                        disabledReason: action.disabledReason,
                        to: action.newTabUrl,
                        targetBlank: action.newTabUrl ? true : undefined,
                        'data-attr': action.dataAttr,
                        onClick: action.onClick,
                    })),
                },
            ]}
        >
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconEllipsis />}
                tooltip="Variant actions"
                aria-label={`Actions for ${props.variantKey}`}
                data-attr="experiment-variant-actions"
            />
        </LemonMenu>
    )
}
