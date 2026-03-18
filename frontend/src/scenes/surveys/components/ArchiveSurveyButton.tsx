import { useActions, useValues } from 'kea'

import { IconArchive } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { surveyLogic } from '../surveyLogic'

export interface ArchiveSurveyButtonProps {
    surveyId: string
    responseUuid: string
}

export function ArchiveSurveyButton({ surveyId, responseUuid }: ArchiveSurveyButtonProps): JSX.Element {
    const { archivedResponseUuids } = useValues(surveyLogic({ id: surveyId }))
    const { archiveResponse, unarchiveResponse } = useActions(surveyLogic({ id: surveyId }))

    const isArchived = archivedResponseUuids?.has(responseUuid) ?? false

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
