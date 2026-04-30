import { useActions } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { SurveyEditSection, surveyLogic } from 'scenes/surveys/surveyLogic'

interface Props {
    section: SurveyEditSection
    label?: string
}

const defaultLabels: Record<SurveyEditSection, string> = {
    [SurveyEditSection.Steps]: 'steps section',
    [SurveyEditSection.Widget]: 'widget section',
    [SurveyEditSection.Presentation]: 'presentation section',
    [SurveyEditSection.Appearance]: 'appearance section',
    [SurveyEditSection.Customization]: 'customization section',
    [SurveyEditSection.DisplayConditions]: 'display conditions section',
    [SurveyEditSection.Scheduling]: 'scheduling section',
    [SurveyEditSection.CompletionConditions]: 'completion conditions section',
}

export function LinkToSurveyFormSection({ section, label }: Props): JSX.Element {
    const { setSelectedSection } = useActions(surveyLogic)

    return <Link onClick={() => setSelectedSection(section)}>{label || defaultLabels[section]}</Link>
}
