import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { Button, Field, Input, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { jsSnippetVersionPinLogic } from './jsSnippetVersionPinLogic'

export function JsSnippetVersionPin(): JSX.Element {
    const { versionPinResponse, versionPinResponseLoading, localPin } = useValues(jsSnippetVersionPinLogic)
    const { saveVersionPin, setLocalPin } = useActions(jsSnippetVersionPinLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const savedPin = versionPinResponse?.requested_version ?? ''
    const resolvedVersion = versionPinResponse?.resolved_version
    const hasChanged = (localPin || null) !== (savedPin || null)

    const handleSave = (): void => saveVersionPin({ pin: localPin || null })

    if (todayRailNav) {
        return (
            <div className="flex max-w-160 flex-col gap-2">
                <Field orientation="horizontal" className="w-fit flex-wrap items-center">
                    <Input
                        size="sm"
                        className="w-32"
                        aria-label="Snippet version"
                        value={localPin}
                        onChange={(event) => setLocalPin(event.target.value)}
                        placeholder="1 (default)"
                        disabled={versionPinResponseLoading}
                        disabledReason={restrictedReason}
                    />
                    <Button
                        variant="primary"
                        onClick={handleSave}
                        loading={versionPinResponseLoading}
                        disabledReason={restrictedReason ?? (!hasChanged ? 'No changes to save' : undefined)}
                    >
                        Save
                    </Button>
                </Field>
                {resolvedVersion && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Currently resolves to: <strong>{resolvedVersion}</strong>
                    </Text>
                )}
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Accepted formats: major version (<code>1</code>), minor version (<code>1.358</code>), or exact
                    version (<code>1.358.0</code>).
                </Text>
            </div>
        )
    }

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
                    onClick={handleSave}
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
