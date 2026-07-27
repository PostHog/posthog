import { LemonDialog } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { Survey, SurveyType } from '~/types'

import { HostedSurveyRespondentHint } from './components/HostedSurveyRespondentHint'
import { getSurveyUrl } from './CopySurveyLink'
import { isSurveyRunning } from './utils'

export function openDeleteSurveyDialog(survey: Pick<Survey, 'start_date'>, onConfirm: () => void): void {
    const isDraft = !survey.start_date
    LemonDialog.open({
        title: 'Permanently delete this survey?',
        content: isDraft ? (
            <div className="text-sm text-secondary">
                <strong>This action cannot be undone.</strong>
            </div>
        ) : (
            <div className="text-sm text-secondary">
                <p>
                    <strong>This action cannot be undone.</strong>
                </p>
                <p className="mt-2">The survey configuration will be permanently deleted.</p>
                <p className="mt-2 text-muted">Note: Survey response events in your data will not be affected.</p>
            </div>
        ),
        primaryButton: {
            children: 'Delete permanently',
            type: 'primary',
            status: 'danger',
            onClick: onConfirm,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

export function openArchiveSurveyDialog(survey: Pick<Survey, 'start_date' | 'end_date'>, onConfirm: () => void): void {
    const isRunning = isSurveyRunning(survey)
    LemonDialog.open({
        title: 'Archive this survey?',
        content: isRunning ? (
            <div className="text-sm text-secondary">
                <p>This survey is currently running. Archiving will:</p>
                <ul className="list-disc ml-4 mt-2">
                    <li>Stop the survey immediately</li>
                    <li>Remove it from your active surveys list</li>
                </ul>
                <p className="mt-2">You can restore this survey at any time from the Archived tab.</p>
            </div>
        ) : (
            <div className="text-sm text-secondary">
                This will remove the survey from your active surveys list. You can restore it at any time from the
                Archived tab.
            </div>
        ),
        primaryButton: {
            children: isRunning ? 'Stop and archive' : 'Archive',
            type: 'primary',
            onClick: onConfirm,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

export function openResumeSurveyDialog(survey: Pick<Survey, 'id' | 'type'>, onConfirm: () => void): void {
    const isHostedSurvey = survey.type === SurveyType.ExternalSurvey

    LemonDialog.open({
        title: 'Resume this survey?',
        content: isHostedSurvey ? (
            <div className="flex flex-col gap-3 text-sm">
                <p className="text-secondary m-0">
                    Once resumed, anyone with the link can answer the survey again. We'll copy the link to your
                    clipboard so you can share it right away.
                </p>
                <HostedSurveyRespondentHint />
            </div>
        ) : (
            <div className="text-sm text-secondary">Once resumed, the survey will be visible to your users again.</div>
        ),
        primaryButton: {
            children: isHostedSurvey ? 'Resume and copy link' : 'Resume',
            type: 'primary',
            onClick: () => {
                if (isHostedSurvey) {
                    void copyToClipboard(getSurveyUrl(survey.id), 'survey link')
                }
                onConfirm()
            },
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

export function canDeleteSurvey(survey: Pick<Survey, 'archived' | 'start_date'>): boolean {
    return survey.archived || !survey.start_date
}
