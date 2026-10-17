import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Survey } from '~/types'

const MAX_LISTED_SURVEYS = 10

export function SurveysOptInConfirmation({ untargetedSurveys }: { untargetedSurveys: Survey[] | null }): JSX.Element {
    if (untargetedSurveys === null) {
        return (
            <p className="m-0 text-sm">
                We could not check which surveys are running. When you turn on surveys, every running popover survey
                without display conditions shows to all users of your app.
            </p>
        )
    }

    const hiddenCount = untargetedSurveys.length - MAX_LISTED_SURVEYS

    return (
        <div className="flex flex-col gap-2 text-sm">
            <p className="m-0">
                {untargetedSurveys.length === 1
                    ? 'This running popover survey has no display conditions.'
                    : `These ${untargetedSurveys.length} running popover surveys have no display conditions.`}{' '}
                When you turn on surveys, your app shows {untargetedSurveys.length === 1 ? 'it' : 'them'} to all users
                right away.
            </p>
            <ul className="list-disc pl-5 m-0">
                {untargetedSurveys.slice(0, MAX_LISTED_SURVEYS).map((survey) => (
                    <li key={survey.id}>
                        <Link to={urls.survey(survey.id)} target="_blank">
                            {survey.name}
                        </Link>
                    </li>
                ))}
                {hiddenCount > 0 && <li>and {hiddenCount} more</li>}
            </ul>
            <p className="m-0 text-secondary">
                To limit who sees a survey, add display conditions to it or stop it before you turn on surveys.
            </p>
        </div>
    )
}
