import './Panels.scss'

import { useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { organizationLogic } from 'scenes/organizationLogic'

import { CardContainer } from '../CardContainer'

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
                        Your demo data is on the way! This can take up to one minute - we'll redirect you when your demo
                        data is ready.
                    </p>
                    <LemonBanner type="info" className="my-6">
                        We're using a demo project. Your other <b>{currentOrganization?.name}</b> projects won't be
                        affected.
                    </LemonBanner>
                </div>
            </div>
        </CardContainer>
    )
}
