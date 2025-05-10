import './AnimatedBackButton.scss'

import { useRef } from 'react'
import { CSSTransition } from 'react-transition-group'

export function AnimatedBackButton({ children, in: inProp }: React.PropsWithChildren<{ in: boolean }>): JSX.Element {
    const backButtonRef = useRef(null)

    return (
        <CSSTransition nodeRef={backButtonRef} in={inProp} timeout={150} classNames="MaxBackButton" unmountOnExit>
            <div ref={backButtonRef} className="inline-block transition-all duration-150 overflow-hidden MaxBackButton">
                {children}
            </div>
        </CSSTransition>
    )
}
