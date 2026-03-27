import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { jsSnippetVersionPinLogic } from './jsSnippetVersionPinLogic'

export function JsSnippetVersionPin(): JSX.Element {
    const { versionPinResponse, versionPinResponseLoading, localPin } = useValues(jsSnippetVersionPinLogic)
    const { saveVersionPin, setLocalPin } = useActions(jsSnippetVersionPinLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedPin = versionPinResponse?.requested_version ?? ''
    const resolvedVersion = versionPinResponse?.resolved_version
    const hasChanged = (localPin || null) !== (savedPin || null)

    return (
        <div className="space-y-4 max-w-160">
            <div className="flex items-center gap-2">
                <LemonInput
                    className="w-32"
                    value={localPin}
                    onChange={setLocalPin}
                    placeholder="1 (default)"
                    disabled={versionPinResponseLoading || !!restrictedReason}
                />
                <LemonButton
                    type="primary"
                    onClick={() => saveVersionPin({ pin: localPin || null })}
                    disabled={!hasChanged || versionPinResponseLoading}
                    loading={versionPinResponseLoading}
                    disabledReason={restrictedReason}
                >
                    Save
                </LemonButton>
            </div>
            {resolvedVersion && (
                <p className="text-muted text-xs">
                    Currently resolves to: <strong>{resolvedVersion}</strong>
                </p>
            )}
            <p className="text-muted text-xs">
                Accepted formats: major version (<code>1</code>), minor version (<code>1.358</code>), or exact version (
                <code>1.358.0</code>).
            </p>
        </div>
    )
}
