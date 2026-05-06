import './AnimatedBackButton.scss'

import clsx from 'clsx'

import { useAnimatedPresence } from 'lib/hooks/useAnimatedPresence'

export function AnimatedBackButton({
    children,
    in: inProp,
}: React.PropsWithChildren<{ in: boolean }>): JSX.Element | null {
    const { rendered, shown } = useAnimatedPresence(inProp, 100)

    if (!rendered) {
        return null
    }

    return (
        <div className={clsx('shrink-0 overflow-hidden MaxBackButton', shown && 'MaxBackButton--visible')}>
            {children}
        </div>
    )
}
