import { useValues } from 'kea'

import { IconDownload } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, Text } from '@posthog/quill'

import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { ExporterFormat } from '~/types'

import { SURVEY_NO_RESPONSES_TO_EXPORT, useSurveyResponsesExport } from './SurveySidebar'

export function QuillSurveyExportPanel(): JSX.Element {
    const { responsesExportQuery } = useValues(surveyLogic)
    const { disabledReason, exportResponses } = useSurveyResponsesExport()

    return (
        <section className="flex flex-col gap-2">
            <Text size="xs" variant="muted" className="m-0">
                Download every response to this survey.
            </Text>
            {responsesExportQuery ? (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={<Button variant="outline" className="self-start" data-attr="export-survey-responses" />}
                    >
                        <IconDownload />
                        Export responses
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start">
                        <DropdownMenuItem
                            disabledReason={disabledReason}
                            onClick={() => exportResponses(ExporterFormat.CSV)}
                        >
                            Export as CSV
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            disabledReason={disabledReason}
                            onClick={() => exportResponses(ExporterFormat.XLSX)}
                        >
                            Export as Excel
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            ) : (
                <Text size="xs" className="m-0">
                    {SURVEY_NO_RESPONSES_TO_EXPORT}
                </Text>
            )}
        </section>
    )
}
