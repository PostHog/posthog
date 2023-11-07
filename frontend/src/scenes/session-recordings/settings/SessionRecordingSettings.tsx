import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SettingsRenderer } from 'scenes/settings/SettingsRenderer'

export function openSessionRecordingSettingsDialog(): void {
    LemonDialog.open({
        title: 'Session recording settings',
        content: <SettingsRenderer sectionId="project-replay" />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}
