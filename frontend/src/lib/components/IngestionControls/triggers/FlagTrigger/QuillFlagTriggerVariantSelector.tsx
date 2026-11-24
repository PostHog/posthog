import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Button, Label, ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { flagTriggerLogic } from './flagTriggerLogic'
import { ANY_VARIANT, selectFlagVariant, variantOptions } from './VariantSelector'

export function QuillFlagTriggerVariantSelector({ tooltip }: { tooltip: JSX.Element }): JSX.Element | null {
    const { flag, featureFlagLoading, linkedFlag, flagHasVariants } = useValues(flagTriggerLogic)
    const { onChange } = useActions(flagTriggerLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (!flagHasVariants) {
        return null
    }

    const options = variantOptions(
        linkedFlag?.filters.multivariate,
        restrictedReason ?? (featureFlagLoading ? 'Loading...' : undefined)
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-1">
                <Label>Link to a specific flag variant</Label>
                <Tooltip>
                    <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="About flag variants" />}>
                        <IconInfo />
                    </TooltipTrigger>
                    <TooltipContent>
                        <div className="flex flex-col gap-1">{tooltip}</div>
                    </TooltipContent>
                </Tooltip>
            </div>
            <ToggleGroup
                variant="outline"
                aria-label="Flag variant"
                className="flex-wrap"
                value={[flag?.variant ?? ANY_VARIANT]}
                onValueChange={(next: string[]) => {
                    if (next[0]) {
                        selectFlagVariant(linkedFlag, next[0], onChange)
                    }
                }}
            >
                {options.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value} disabledReason={option.disabledReason}>
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}
