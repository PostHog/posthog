import { useActions, useValues } from 'kea'

import { IconArchive, IconRevert } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { surveyLogic } from './surveyLogic'

interface SurveyResponseRowActionsProps {
    responseUuid: string
}

export function SurveyResponseRowActions({ responseUuid }: SurveyResponseRowActionsProps): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const { archiveSurveyResponse, unarchiveSurveyResponse } = useActions(surveyLogic)

    const isArchived = survey.archived_response_uuids?.includes(responseUuid)

    return (
        <More
            overlay={
                <>
                    {isArchived ? (
                        <LemonButton
                            icon={<IconRevert />}
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Unarchive this response?',
                                    content: (
                                        <div className="text-sm text-secondary">
                                            This response will be visible again in all views and exports.
                                        </div>
                                    ),
                                    primaryButton: {
                                        children: 'Unarchive',
                                        type: 'primary',
                                        onClick: () => unarchiveSurveyResponse(responseUuid),
                                        size: 'small',
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                        type: 'tertiary',
                                        size: 'small',
                                    },
                                })
                            }}
                            fullWidth
                            data-attr="survey-response-unarchive"
                        >
                            Unarchive response
                        </LemonButton>
                    ) : (
                        <LemonButton
                            icon={<IconArchive />}
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Archive this response?',
                                    content: (
                                        <div className="text-sm text-secondary">
                                            This response will be hidden from all views and exports. You can restore it
                                            later.
                                        </div>
                                    ),
                                    primaryButton: {
                                        children: 'Archive',
                                        type: 'primary',
                                        onClick: () => archiveSurveyResponse(responseUuid),
                                        size: 'small',
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                        type: 'tertiary',
                                        size: 'small',
                                    },
                                })
                            }}
                            fullWidth
                            data-attr="survey-response-archive"
                        >
                            Archive response
                        </LemonButton>
                    )}
                </>
            }
        />
    )
}
