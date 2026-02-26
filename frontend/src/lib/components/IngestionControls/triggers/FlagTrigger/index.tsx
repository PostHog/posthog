import { BindLogic } from 'kea'
import { PropsWithChildren, type JSX } from 'react'

import { FlagTriggerLogicProps, flagTriggerLogic } from './flagTriggerLogic'

export default function FlagTrigger({ children, ...props }: PropsWithChildren<FlagTriggerLogicProps>): JSX.Element {
    return (
        <BindLogic logic={flagTriggerLogic} props={props}>
            {children}
        </BindLogic>
    )
}
