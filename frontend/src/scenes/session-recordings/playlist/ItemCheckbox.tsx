import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'

import { SessionRecordingType } from '~/types'

import { useRecordingSelection } from './useRecordingSelection'

export function ItemCheckbox({ recording }: { recording: SessionRecordingType }): JSX.Element {
    const { checked, disabledReason, toggle } = useRecordingSelection(recording)

    return (
        <LemonCheckbox
            checked={checked}
            data-attr="select-recording"
            aria-label="Select recording"
            disabledReason={disabledReason}
            onChange={toggle}
            stopPropagation
        />
    )
}
