import { useValues } from 'kea'

import { HedgehogModeStatic } from 'lib/components/HedgehogMode/HedgehogModeStatic'
import { hedgehogModeLogic } from 'lib/components/HedgehogMode/hedgehogModeLogic'

import { maxLogic } from './maxLogic'

export function Intro(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
    const { headline, description } = useValues(maxLogic)

    return (
        <>
            <div className="flex">
                <HedgehogModeStatic config={hedgehogConfig} size={80} direction="left" />
            </div>
            <div className="mb-1 text-center">
                <h2 className="text-xl @md/max-welcome:text-2xl font-bold mb-2 text-balance">{headline}</h2>
                <div className="text-sm text-secondary text-pretty">{description}</div>
            </div>
        </>
    )
}
