import { router } from 'kea-router'

import { NotFound } from 'lib/components/NotFound'
import { Link } from 'lib/lemon-ui/Link'
import { SETTINGS_LOGIC_KEY } from 'scenes/session-recordings/settings/SessionRecordingsSettingsScene'
import { Settings } from 'scenes/settings/Settings'

export function RecordingNotFound(): JSX.Element {
    return (
        <NotFound
            object="Recording"
            caption={
                <>
                    The requested recording doesn't seem to exist. The recording may still be processing, deleted due to
                    age or have not been enabled. Please check your project replay settings below. Alternatively read
                    the{' '}
                    <Link to="https://posthog.com/docs/session-replay/troubleshooting#recording-not-found">
                        troubleshooting guide
                    </Link>
                    <h3 className="mb-2 mt-8">Project replay settings</h3>
                    <div className="mt-4 border rounded-md p-4 text-left">
                        <Settings
                            logicKey={SETTINGS_LOGIC_KEY}
                            sectionId="environment-replay"
                            settingId={router.values.searchParams.sectionId || 'replay'}
                            handleLocally
                        />
                    </div>
                </>
            }
        />
    )
}
