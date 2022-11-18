import { useValues } from 'kea'
import { AlertMessage } from 'lib/components/AlertMessage'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { organizationLogic } from 'scenes/organizationLogic'
import { CardContainer } from '../CardContainer'
import './Panels.scss'

export function GeneratingDemoDataPanel(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    return (
        <CardContainer>
            <div className="">
                <div className="ingestion-generating-demo-data m-6">
                    <div className="w-full flex justify-center my-6">
                        <Spinner className="text-4xl" />
                    </div>
                    <h1 className="ingestion-title pt-4">Generating demo data...</h1>
                    <p className="prompt-text mx-0">
                        This will take just a moment - we'll redirect you when your demo data is ready.
                    </p>
                    <AlertMessage type="info" className="my-6">
                        We're using a demo project. Your <b>{currentOrganization?.name}</b> project is still a clean
                        slate.
                    </AlertMessage>
                </div>
            </div>
        </CardContainer>
    )
}
