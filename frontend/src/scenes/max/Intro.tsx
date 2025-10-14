import { useValues } from 'kea'

import { Logomark } from '~/toolbar/assets/Logomark'

import { maxLogic } from './maxLogic'

export function Intro(): JSX.Element {
    const { headline } = useValues(maxLogic)

    return (
        <>
            <div className="flex">
                <Logomark />
            </div>
            <div className="text-center mb-1">
                <h2 className="text-xl @md/max-welcome:text-2xl font-bold my-2 text-balance">{headline}</h2>
            </div>
        </>
    )
}
