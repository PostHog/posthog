import { useActions, useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

export type SurveySettingsProps = {
    inModal?: boolean
}

export function SurveySettings({ inModal = false }: SurveySettingsProps): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="space-y-4">
            <div className="space-y-2">
                <LemonSwitch
                    data-attr="opt-in-surveys-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            surveys_opt_in: checked,
                        })
                    }}
                    label="Enable surveys popup"
                    bordered={!inModal}
                    fullWidth={inModal}
                    labelClassName={inModal ? 'text-base font-semibold' : ''}
                    checked={!!currentTeam?.surveys_opt_in}
                />

                <p>
                    Please note your website needs to have the{' '}
                    <Link to={urls.projectSettings() + '#snippet'}>PostHog snippet</Link> or the latest version of{' '}
                    <Link
                        to="https://posthog.com/docs/integrations/js-integration?utm_campaign=surveys&utm_medium=in-product"
                        target="_blank"
                    >
                        posthog-js
                    </Link>{' '}
                    directly installed. For more details, check out our{' '}
                    <Link
                        to="https://posthog.com/docs/surveys/installation?utm_campaign=surveys&utm_medium=in-product"
                        target="_blank"
                    >
                        docs
                    </Link>
                    .
                </p>
            </div>
        </div>
    )
}

export function openSurveysSettingsDialog(): void {
    LemonDialog.open({
        title: 'Surveys settings',
        content: <SurveySettings inModal />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}
