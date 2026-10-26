import { useActions, useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'

import { AvailableFeature } from '~/types'

import { accessControlLogic } from '../accessControlLogic'
import { QuillAccessLevelSelect } from './QuillAccessLevelSelect'

export function QuillAccessControlDefaults(): JSX.Element {
    const { accessControlDefault, accessControls, accessControlsLoading, availableLevelsWithNone, inheritedAccess } =
        useValues(accessControlLogic)
    const { updateAccessControlDefault } = useActions(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    if (!accessControls) {
        // A null level is a real state ("No override") for this select, so it can't double as the loading state.
        return <Skeleton className="h-7 w-40" />
    }

    return (
        <QuillAccessLevelSelect
            // A null level renders as the "No override" option, which only exists when there is
            // an inherited tier. With nothing to inherit (project/organization), a missing row
            // means the built-in default applies, so show that rather than an empty selection.
            level={accessControlDefault?.access_level ?? (inheritedAccess ? null : accessControls.default_access_level)}
            levels={availableLevelsWithNone}
            inherited={inheritedAccess}
            disabledReason={accessControlsLoading ? 'Loading…' : undefined}
            onChange={(newValue) => {
                guardAvailableFeature(AvailableFeature.ACCESS_CONTROL, () => {
                    updateAccessControlDefault(newValue)
                })
            }}
        />
    )
}
