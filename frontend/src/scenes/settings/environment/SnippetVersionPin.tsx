import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { snippetVersionPinLogic } from './snippetVersionPinLogic'

export function SnippetVersionPin(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { versionPin, resolvedVersion, loading, saving } = useValues(snippetVersionPinLogic)
    const { loadVersionPin, saveVersionPin } = useActions(snippetVersionPinLogic)
    const [localPin, setLocalPin] = useState(versionPin ?? '')

    useEffect(() => {
        if (currentTeam) {
            loadVersionPin()
        }
    }, [currentTeam?.id, currentTeam, loadVersionPin])

    useEffect(() => {
        setLocalPin(versionPin ?? '')
    }, [versionPin])

    const hasChanged = (localPin || null) !== (versionPin || null)

    return (
        <div className="space-y-4 max-w-160">
            <div className="flex items-center gap-2">
                <LemonInput
                    className="w-32"
                    value={localPin}
                    onChange={setLocalPin}
                    placeholder="1 (default)"
                    disabled={loading}
                />
                <LemonButton
                    type="primary"
                    onClick={() => saveVersionPin(localPin || null)}
                    disabled={!hasChanged || saving}
                    loading={saving}
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
