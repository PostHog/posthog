import './SurveyView.scss'

import { SurveyNotificationModal } from 'scenes/surveys/components/SurveyNotificationModal'
import { SurveyViewRedesign } from 'scenes/surveys/SurveyViewRedesign/SurveyViewRedesign'

export function SurveyView({ id }: { id: string }): JSX.Element {
    return (
        <>
            <SurveyViewRedesign />
            <SurveyNotificationModal surveyId={id} />
        </>
    )
}
