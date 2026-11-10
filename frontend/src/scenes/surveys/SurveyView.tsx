import './SurveyView.scss'

import { UseMaxToolReturn } from 'scenes/max/useMaxTool'
import { SurveyNotificationModal } from 'scenes/surveys/components/SurveyNotificationModal'
import { SurveyViewRedesign } from 'scenes/surveys/SurveyViewRedesign/SurveyViewRedesign'

export function SurveyView({ id, openMax }: { id: string; openMax: UseMaxToolReturn['openMax'] }): JSX.Element {
    return (
        <>
            <SurveyViewRedesign openMax={openMax} />
            <SurveyNotificationModal surveyId={id} />
        </>
    )
}
