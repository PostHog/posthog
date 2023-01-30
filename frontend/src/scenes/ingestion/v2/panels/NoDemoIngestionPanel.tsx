import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconArrowRight } from 'lib/lemon-ui/icons'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'
import { CardContainer } from '../CardContainer'
import './Panels.scss'

export function NoDemoIngestionPanel(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { updateCurrentTeam } = useActions(userLogic)

    return (
        <CardContainer>
            <div className="ingestion-generating-demo-data m-6">
                <h1 className="ingestion-title pt-4">Whoops!</h1>
                <p className="prompt-text mx-0">
                    New events can't be ingested into a demo project. But, you can switch to another project if you'd
                    like:
                </p>
                <div className="w-60 flex flex-col m-auto">
                    {currentOrganization?.teams
                        ?.filter((team) => !team.is_demo)
                        .map((team) => (
                            <p key={team.id}>
                                <LemonButton
                                    type="secondary"
                                    sideIcon={<IconArrowRight />}
                                    fullWidth
                                    onClick={() => updateCurrentTeam(team.id)}
                                >
                                    {team.name}
                                </LemonButton>
                            </p>
                        ))}
                </div>
            </div>
        </CardContainer>
    )
}
