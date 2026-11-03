import { Checkbox } from '@posthog/quill'

import { SessionRecordingType } from '~/types'

import { useRecordingSelection } from './useRecordingSelection'

export function QuillItemCheckbox({ recording }: { recording: SessionRecordingType }): JSX.Element {
    const { checked, disabledReason, toggle } = useRecordingSelection(recording)

    return (
        // The row behind the checkbox opens the recording on click, so the click must stop here.
        <span className="inline-flex" onClick={(e) => e.stopPropagation()}>
            <Checkbox
                checked={checked}
                data-attr="select-recording"
                aria-label="Select recording"
                disabledReason={disabledReason}
                onCheckedChange={toggle}
            />
        </span>
    )
}
