import { useActions, useValues } from 'kea'

import { IconArchive } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { surveyLogic } from '../surveyLogic'

export interface ArchiveSurveyButtonProps {
    responseUuid: string
}

export function ArchiveSurveyButton({ responseUuid }: ArchiveSurveyButtonProps): JSX.Element {
    const { archivedResponseUuids } = useValues(surveyLogic)
    const { archiveResponse, unarchiveResponse } = useActions(surveyLogic)

    const isArchived = archivedResponseUuids.has(responseUuid)

    return (
        <LemonButton
            onClick={() => {
                if (responseUuid) {
                    isArchived ? unarchiveResponse(responseUuid) : archiveResponse(responseUuid)
                }
            }}
            fullWidth
            sideIcon={<IconArchive />}
            data-attr="events-table-archive-survey"
        >
            {isArchived ? 'Unarchive' : 'Archive'} response
        </LemonButton>
    )
}
