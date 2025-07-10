import './AnimatedBackButton.scss'

import { useRef } from 'react'
import { CSSTransition } from 'react-transition-group'

export function AnimatedBackButton({ children, in: inProp }: React.PropsWithChildren<{ in: boolean }>): JSX.Element {
    const backButtonRef = useRef(null)

    return (
        <CSSTransition nodeRef={backButtonRef} in={inProp} timeout={100} classNames="MaxBackButton" unmountOnExit>
            <div ref={backButtonRef} className="MaxBackButton shrink-0 overflow-hidden transition-all duration-100">
                {children}
            </div>
        </CSSTransition>
    )
}
