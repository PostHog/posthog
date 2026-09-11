import { useState } from 'react'

import { LemonCheckbox } from '@posthog/lemon-ui'

export function EnableSurveysCheckbox({ onChange }: { onChange: (enabled: boolean) => void }): JSX.Element {
    const [enabled, setEnabled] = useState(true)

    return (
        <div className="flex flex-col gap-1">
            <LemonCheckbox
                checked={enabled}
                onChange={(checked) => {
                    setEnabled(checked)
                    onChange(checked)
                }}
                label="Enable surveys for this project"
                data-attr="launch-survey-enable-surveys"
                size="small"
            />
            <div className="text-xs text-secondary">
                {enabled
                    ? 'Every running survey in this project starts to show to users, not only this one.'
                    : 'This survey launches, but it stays hidden until surveys are enabled for the project.'}
            </div>
        </div>
    )
}
