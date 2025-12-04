import { BindLogic } from 'kea'
import { PropsWithChildren } from 'react'

import { TriggersLogicProps, triggersLogic } from './triggersLogic'

export function Triggers({ children, ...props }: PropsWithChildren<TriggersLogicProps>): JSX.Element {
    return (
        <BindLogic logic={triggersLogic} props={props}>
            {children}
        </BindLogic>
    )
}
