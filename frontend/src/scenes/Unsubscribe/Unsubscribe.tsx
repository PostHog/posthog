import React from 'react'
import './Unsubscribe.scss'
import { SceneExport } from 'scenes/sceneTypes'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import { unsubscribeLogic } from './unsubscribeLogic'
import { useValues } from 'kea'
import { Spinner } from 'lib/components/Spinner/Spinner'

export const scene: SceneExport = {
    component: Unsubscribe,
    logic: unsubscribeLogic,
}

export function Unsubscribe(): JSX.Element {
    const { unsubscriptionLoading, unsubscription } = useValues(unsubscribeLogic)
    return (
        <div className="Unsubscribe text-center gap">
            <div className="mb">
                <WelcomeLogo view="unsubscribe" />
            </div>

            {unsubscriptionLoading ? (
                <div className="pa">
                    <Spinner />
                </div>
            ) : unsubscription ? (
                <div>
                    <h2>You have been unsubscribed!</h2>
                    <p>If you didn't mean to do that click here and we will re-subscribe you!</p>
                </div>
            ) : (
                <div>
                    <h2>Something went wrong!</h2>
                    <p>Your may already be unsubscribed or the link you clicked may be invalid.</p>
                </div>
            )}
        </div>
    )
}

export default Unsubscribe
