import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Scene } from 'scenes/sceneTypes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import {
    getPickerVariant,
    NEW_INSIGHT_PICKER_VARIANTS,
    NewInsightPickerVariant,
    PickerVariantSwitcher,
} from './newInsightMenuPrototypes'

export function NewInsightMenuOverlay({ variant }: { variant?: NewInsightPickerVariant }): JSX.Element {
    const spec =
        NEW_INSIGHT_PICKER_VARIANTS.find((candidate) => candidate.key === variant) ?? NEW_INSIGHT_PICKER_VARIANTS[0]
    const VariantComponent = spec.component
    return <VariantComponent />
}

export function NewInsightButton(): JSX.Element {
    const { searchParams } = useValues(router)
    const variant = getPickerVariant(searchParams['variant'])

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.Insight}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <Shortcut
                    name="NewInsight"
                    keybind={[keyBinds.new]}
                    intent="New insight"
                    interaction="click"
                    scope={Scene.SavedInsights}
                    priority={100}
                >
                    {/* closeOnClickInside=false so variant E's step switch doesn't dismiss the dropdown;
                        card clicks navigate away regardless */}
                    <LemonDropdown
                        overlay={<NewInsightMenuOverlay variant={variant} />}
                        placement="bottom-end"
                        closeOnClickInside={false}
                    >
                        <LemonButton
                            type="primary"
                            data-attr="saved-insights-new-insight-button"
                            size="small"
                            icon={<IconPlusSmall />}
                            tooltip="New insight"
                        >
                            New
                        </LemonButton>
                    </LemonDropdown>
                </Shortcut>
            </AccessControlAction>
            <PickerVariantSwitcher />
        </>
    )
}
