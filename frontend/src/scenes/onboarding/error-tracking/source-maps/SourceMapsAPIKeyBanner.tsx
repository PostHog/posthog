import { useActions } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { API_KEY_SCOPE_PRESETS } from 'lib/scopes'
import { personalAPIKeysLogic } from 'scenes/settings/user/personalAPIKeysLogic'

export function SourceMapsAPIKeyBanner(): JSX.Element {
    const { setEditingKeyId, setEditingKeyValues } = useActions(personalAPIKeysLogic)

    const openAPIKeyModal = (): void => {
        const preset = API_KEY_SCOPE_PRESETS.find((p) => p.value === 'source_map_upload')
        if (preset) {
            setEditingKeyId('new')
            setEditingKeyValues({
                preset: preset.value,
                label: preset.label,
                scopes: preset.scopes,
                access_type: preset.access_type,
            })
        }
    }

    return (
        <LemonBanner type="info" className="mb-4">
            <div className="flex items-center gap-2 justify-between">
                The project API key used to initialize PostHog is not the same as the personal API key required to
                upload source maps. If you want to upload source maps, you can create a personal API key here.
                <LemonButton type="primary" onClick={openAPIKeyModal}>
                    Create personal API key
                </LemonButton>
            </div>
        </LemonBanner>
    )
}
