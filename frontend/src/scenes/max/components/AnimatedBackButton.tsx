import './AnimatedBackButton.scss'

import { useRef } from 'react'
import { CSSTransition } from 'react-transition-group'

export function AnimatedBackButton({ children, in: inProp }: React.PropsWithChildren<{ in: boolean }>): JSX.Element {
    const backButtonRef = useRef(null)

    return (
        <CSSTransition nodeRef={backButtonRef} in={inProp} timeout={100} classNames="MaxBackButton" unmountOnExit>
            <div ref={backButtonRef} className="shrink-0 transition-all duration-100 overflow-hidden MaxBackButton">
                {children}
            </div>
        </CSSTransition>
    )
}
