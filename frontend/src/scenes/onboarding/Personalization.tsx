import { useValues } from 'kea'
import React from 'react'
import { hot } from 'react-hot-loader/root'
import { personalizationLogic } from './personalizationLogic'

export const Personalization = hot(_Personalization)

function _Personalization(): JSX.Element {
    const { step } = useValues(personalizationLogic)
    return (
        <div>
            Personalize me! <span>Step {step}</span>
        </div>
    )
}
